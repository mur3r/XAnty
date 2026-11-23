"""Bounded CDP sessions for background diagnostics without switching user tabs."""
import ipaddress
import json
import time
from collections import deque
from contextlib import contextmanager
from urllib.parse import urlsplit

import requests
import websocket


class CdpError(RuntimeError):
    pass


class CdpConnection:
    def __init__(self,socket,timeout=12):
        self.socket=socket;self.timeout=timeout;self.sequence=0;self.events=deque(maxlen=512)
        self.hidden_supported=False

    def _receive(self,deadline):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise CdpError('Browser diagnostic timed out')
        try:
            self.socket.settimeout(remaining)
            raw=self.socket.recv()
            if not raw or len(raw)>8*1024*1024:raise CdpError('Invalid browser diagnostic response')
            data=json.loads(raw)
            if not isinstance(data,dict):raise CdpError('Invalid browser diagnostic response')
            return data
        except CdpError:raise
        except Exception:raise CdpError('Browser diagnostic connection failed or timed out') from None

    def call(self,method,params=None,session_id=None,timeout=None):
        self.sequence+=1;sequence=self.sequence
        message={'id':sequence,'method':method,'params':params or {}}
        if session_id:message['sessionId']=session_id
        try:self.socket.send(json.dumps(message))
        except Exception:raise CdpError('Browser diagnostic connection is unavailable') from None
        deadline=time.monotonic()+(self.timeout if timeout is None else timeout)
        while True:
            response=self._receive(deadline)
            if response.get('id')==sequence:
                if 'error' in response:raise CdpError('Browser diagnostic command failed: '+method)
                return response.get('result',{})
            if 'method' in response:self.events.append(response)

    def wait_event(self,method,session_id=None,predicate=None,timeout=None):
        deadline=time.monotonic()+(self.timeout if timeout is None else timeout)
        def matches(event):
            return (event.get('method')==method and (session_id is None or event.get('sessionId')==session_id)
                    and (predicate is None or predicate(event.get('params',{}))))
        for event in list(self.events):
            if matches(event):self.events.remove(event);return event.get('params',{})
        while True:
            event=self._receive(deadline)
            if matches(event):return event.get('params',{})
            if 'method' in event:self.events.append(event)


def _debug_address(browser):
    address=browser.capabilities.get('goog:chromeOptions',{}).get('debuggerAddress','')
    try:
        parsed=urlsplit('http://'+address)
        host=parsed.hostname
        if (not address or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
                or not parsed.port or not (host=='localhost' or ipaddress.ip_address(host).is_loopback)):
            raise ValueError()
    except (TypeError,ValueError):raise CdpError('A local Chrome diagnostic endpoint is required') from None
    return address,host,parsed.port


@contextmanager
def browser_connection(browser,timeout=12):
    address,host,port=_debug_address(browser)
    socket=None
    try:
        with requests.Session() as session:
            session.trust_env=False
            response=session.get('http://'+address+'/json/version',timeout=(2,min(timeout,5)),allow_redirects=False)
            if response.status_code!=200:raise CdpError('Chrome diagnostic endpoint is unavailable')
            endpoint=response.json().get('webSocketDebuggerUrl','')
            parsed=urlsplit(endpoint)
            if (parsed.scheme!='ws' or parsed.hostname!=host or parsed.port!=port or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or not parsed.path.startswith('/devtools/browser/')):
                raise CdpError('Invalid local Chrome diagnostic endpoint')
            hidden=False
            try:
                protocol=session.get('http://'+address+'/json/protocol',timeout=(2,min(timeout,5)),allow_redirects=False)
                if protocol.status_code==200:
                    hidden=any(p.get('name')=='hidden' for domain in protocol.json().get('domains',[]) if domain.get('domain')=='Target'
                               for command in domain.get('commands',[]) if command.get('name')=='createTarget'
                               for p in command.get('parameters',[]))
            except (requests.RequestException,ValueError,TypeError):pass
        socket=websocket.create_connection(endpoint,suppress_origin=True,timeout=timeout)
        connection=CdpConnection(socket,timeout);connection.hidden_supported=hidden
        yield connection
    except CdpError:raise
    except (requests.RequestException,ValueError,TypeError,websocket.WebSocketException):
        raise CdpError('Chrome diagnostic endpoint is unavailable') from None
    finally:
        if socket is not None:
            try:socket.close()
            except Exception:pass


class BackgroundTarget:
    def __init__(self,connection,target_id,session_id):
        self.connection=connection;self.target_id=target_id;self.session_id=session_id

    def evaluate(self,expression,await_promise=True,timeout=8):
        response=self.connection.call('Runtime.evaluate',{'expression':expression,'awaitPromise':await_promise,
            'returnByValue':True,'timeout':max(1,int(timeout*1000))},session_id=self.session_id,timeout=timeout+1)
        if response.get('exceptionDetails') or response.get('result',{}).get('subtype')=='error':
            raise CdpError('Browser diagnostic script failed')
        return response.get('result',{}).get('value')


@contextmanager
def background_target(browser,url='about:blank',timeout=12):
    with browser_connection(browser,timeout) as connection:
        target_id=None
        try:
            parameters={'url':'about:blank','background':True}
            if connection.hidden_supported:parameters['hidden']=True
            target_id=connection.call('Target.createTarget',parameters)['targetId']
            session_id=connection.call('Target.attachToTarget',{'targetId':target_id,'flatten':True})['sessionId']
            if url!='about:blank':connection.call('Page.navigate',{'url':url},session_id=session_id)
            yield BackgroundTarget(connection,target_id,session_id)
        finally:
            if target_id is not None:
                try:
                    connection.call('Target.closeTarget',{'targetId':target_id},timeout=2)
                    deadline=time.monotonic()+2
                    while time.monotonic()<deadline:
                        targets=connection.call('Target.getTargets',timeout=2).get('targetInfos',[])
                        if not any(t.get('targetId')==target_id for t in targets):break
                        time.sleep(.03)
                except CdpError:pass
