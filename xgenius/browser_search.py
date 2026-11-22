"""Repair the portable Chrome build's 'No Search' omnibox provider."""


class SearchConfigurationError(RuntimeError):
    pass


SEARCH_SETTINGS_SCRIPT = r"""
const done = arguments[arguments.length - 1];
(async () => {
  const findPage = root => {
    for (const element of root.querySelectorAll('*')) {
      if (element.tagName === 'SETTINGS-SEARCH-ENGINES-PAGE') return element;
      const found = element.shadowRoot && findPage(element.shadowRoot);
      if (found) return found;
    }
    return null;
  };
  let page;
  for (let attempt = 0; attempt < 40; attempt++) {
    page = findPage(document);
    if (page?.browserProxy_) break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  const proxy = page?.browserProxy_;
  if (!proxy) throw new Error('Chrome search settings are not available');
  const read = async () => Object.values(await proxy.getSearchEnginesList())
    .filter(Array.isArray).flat();
  const broken = engine => !engine || engine.keyword === 'nosearch' ||
    /^https?:\/\/(?:%s|\{searchTerms\})\/?$/i.test(engine.url || '');
  const google = engine => /^https:\/\/(?:www\.)?google\.com\/search\?/i.test(engine.url || '');
  let engines = await read();
  let current = engines.find(engine => engine.default);
  if (!broken(current)) return {ok: true, changed: false, url: current.url};
  let candidate = engines.find(google);
  if (!candidate) {
    const keyword = engines.some(engine => engine.keyword === 'google.com') ? 'xanty-google' : 'google.com';
    proxy.searchEngineEditStarted(-1);
    // The bundled Chrome fork adds a fourth suggestions-URL argument. Calling
    // its own frontend proxy also works with standard Chrome's three arguments.
    proxy.searchEngineEditCompleted('Google', keyword, 'https://www.google.com/search?q=%s',
      'https://www.google.com/complete/search?client=chrome&q=%s');
    engines = await read();
    candidate = engines.find(google);
  }
  if (!candidate || !Number.isInteger(candidate.modelIndex)) throw new Error('Search provider was not created');
  if (candidate.canBeActivated || candidate.isActive === false) {
    proxy.setIsActiveSearchEngine(candidate.modelIndex, true);
    await read();
  }
  proxy.setDefaultSearchEngine(candidate.modelIndex, 1);
  current = (await read()).find(engine => engine.default);
  if (!current || !google(current)) throw new Error('Default search provider was not changed');
  return {ok: true, changed: true, url: current.url};
})().then(done).catch(error => done({ok: false, error: String(error)}));
"""


def ensure_search_engine(browser) -> dict:
    """Use Chrome's settings API so the choice persists in existing profiles too."""
    browser.get('chrome://settings/searchEngines')
    try:
        result = browser.execute_async_script(SEARCH_SETTINGS_SCRIPT)
    except Exception as exc:
        raise SearchConfigurationError('Could not configure Chrome search. Try opening the profile again.') from exc
    if not isinstance(result, dict) or not result.get('ok'):
        raise SearchConfigurationError('Could not configure Chrome search. Try opening the profile again.')
    return result
