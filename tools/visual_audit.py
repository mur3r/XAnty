"""Real Chromium-on-Windows rendering audit against loopback synthetic fixtures."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.ci-visual'
RESULTS = []
IMAGES = []
ERRORS = []
BASE = ''


def reset(theme='dark', language='ru', **options):
    query = urllib.parse.urlencode(dict(theme=theme, language=language, **options))
    request = urllib.request.Request(BASE + '/__qa/reset?' + query, data=b'{}', method='POST')
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200


def settle(page):
    page.wait_for_function("!document.querySelector('[class*=\"motion-enter-\"]')", timeout=5000)


def screenshot(page, name, embed=False):
    settle(page)
    geometry = page.locator('.modal-overlay:not([inert]) [role="dialog"]').evaluate_all("""els=>els.map(el=>{
      const box=el.getBoundingClientRect(),body=el.querySelector('.modal-body');
      return {left:box.left,right:box.right,top:box.top,bottom:box.bottom,width:innerWidth,height:innerHeight,
        bodyWidth:body.clientWidth,bodyScroll:body.scrollWidth};
    })""")
    path = OUTPUT / (name + '.jpg')
    page.screenshot(path=str(path), type='jpeg', quality=65, animations='disabled')
    IMAGES.append(path)
    embed = embed or (name.startswith('dark-ru-laptop-') and not name.endswith('-profiles')) or name in [
        'light-en-desktop-workspace', 'light-en-desktop-monitor', 'dark-uk-narrow-workspace']
    if embed:
        data = base64.b64encode(path.read_bytes()).decode('ascii')
        print('VISUAL_IMAGE_BEGIN ' + path.name, flush=True)
        for i in range(0, len(data), 4096):
            print(f'VISUAL_IMAGE_CHUNK {path.name} {i // 4096} {data[i:i + 4096]}', flush=True)
        print('VISUAL_IMAGE_END ' + path.name, flush=True)
    assert all(g['left'] >= -1 and g['right'] <= g['width'] + 1 and g['top'] >= -1
               and g['bottom'] <= g['height'] + 1 and g['bodyScroll'] <= g['bodyWidth'] + 1 for g in geometry), geometry


def modal(page):
    return page.locator('.modal-overlay:not([inert])').last


def close_modal(page):
    modal(page).locator('[data-close]').click()
    page.wait_for_function("!document.querySelector('.modal-overlay:not([inert])')")
    page.wait_for_function("!document.querySelector('.modal-overlay')")


def open_navigation(page):
    if page.viewport_size['width'] <= 650:
        button = page.locator('#btn-sidebar-toggle')
        if button.get_attribute('aria-expanded') != 'true':
            button.click()


def close_navigation(page):
    if page.viewport_size['width'] <= 650 and page.locator('#btn-sidebar-toggle').get_attribute('aria-expanded') == 'true':
        page.locator('#btn-sidebar-close').click()


def audit_dimensions(page):
    box = page.evaluate("""() => ({
      width: innerWidth, scroll: document.documentElement.scrollWidth,
      tableRows: document.querySelectorAll('#rows tr').length,
      missingLabels: [...document.querySelectorAll('[data-i18n-aria-label]')].filter(e=>!e.getAttribute('aria-label')).length
    })""")
    assert box['scroll'] <= box['width'] + 1, f'document horizontal overflow: {box}'
    assert box['tableRows'] == 50, box
    assert box['missingLabels'] == 0, box
    expect(page.locator('.app-footer [data-update-open]')).to_be_visible()
    expect(page.locator('.app-footer [data-tool="stop_all"]')).to_be_visible()
    for selector in ['#f-profile-status', '#f-status', '#f-proxy', '#profile-sort']:
        size = page.locator(selector).evaluate("""el => {
          const style=getComputedStyle(el),ctx=new OffscreenCanvas(1,1).getContext('2d');
          ctx.font=style.font||`${style.fontSize} ${style.fontFamily}`;
          return {text:el.selectedOptions[0].text, available:el.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),
            needed:ctx.measureText(el.selectedOptions[0].text).width};
        }""")
        assert size['needed'] <= size['available'] + 2, f'clipped filter {selector}: {size}'


def audit_editor(page, name, embed=False, nested=False):
    page.locator('.header-actions [data-tool="add"]').click()
    active = modal(page)
    expect(active.locator('.account-form [name]')).to_have_count(27)
    active.locator('.account-form details.advanced summary').click()
    active.locator('[name="window_height"]').fill('900')
    dimensions = active.locator('.modal-body').evaluate("""el=>({width:el.clientWidth,scroll:el.scrollWidth,
      top:el.getBoundingClientRect().top,bottom:el.getBoundingClientRect().bottom,viewport:innerHeight})""")
    assert dimensions['scroll'] <= dimensions['width'] + 1, dimensions
    assert dimensions['top'] >= 0 and dimensions['bottom'] <= dimensions['viewport'], dimensions
    active.locator('[name="profile_name"]').fill('QA visual audit')
    active.locator('[name="username"]').fill('qa_visual')
    if nested:
        active.locator('[data-extension-manage]').click()
        expect(page.locator('.modal-overlay')).to_have_count(2)
        expect(page.locator('.modal-overlay:not([inert])')).to_have_count(1)
        ids = page.locator('[role="dialog"]').evaluate_all("els=>els.map(el=>el.getAttribute('aria-labelledby'))")
        assert len(set(ids)) == 2, ids
        modal(page).locator('[data-close]').press('Escape')
        expect(page.locator('.modal-overlay:not([inert]) .account-form')).to_be_visible()
        page.wait_for_function("document.querySelectorAll('.modal-overlay').length===1")
    # Screenshot the first two visual groups after testing the bottom of the form.
    active.locator('[name="profile_name"]').focus()
    active.locator('.modal-body').evaluate('el=>el.scrollTop=0')
    screenshot(page, name, embed)
    active.locator('.modal-foot button').last.focus()
    page.keyboard.press('Tab')
    assert page.evaluate("document.activeElement.hasAttribute('data-close')"), 'focus did not wrap to close'
    page.keyboard.press('Shift+Tab')
    assert page.evaluate("document.activeElement.closest('.modal-foot')!==null"), 'reverse focus trap failed'
    close_modal(page)


def audit_file_control(page):
    active = modal(page)
    control = active.locator('.file-control')
    expect(control.locator('.file-control-action')).to_have_text(page.evaluate("t('quality_file_choose')"))
    expect(control.locator('[data-file-name]')).to_have_text(page.evaluate("t('quality_file_empty')"))
    field = control.locator('input[type=file]')
    cookie_file = '.json' in (field.get_attribute('accept') or '')
    filename = 'QA-довга-назва.json' if cookie_file else 'QA-довга-назва.xanty'
    field.set_input_files(dict(name=filename, mimeType='application/json' if cookie_file else 'application/zip',
                              buffer=b'[]' if cookie_file else b'synthetic, not an imported archive'))
    expect(control.locator('[data-file-name]')).to_have_text(filename)
    field.focus()
    page.keyboard.press('Tab')
    page.keyboard.press('Shift+Tab')
    expect(field).to_be_focused()
    assert control.evaluate("el=>getComputedStyle(el).outlineStyle") != 'none', 'file control lacks a visible keyboard focus ring'
    field.set_input_files([])
    expect(control.locator('[data-file-name]')).to_have_text(page.evaluate("t('quality_file_empty')"))


def audit_notes_and_logs(page, label):
    page.locator('.rail [data-tab="profiles"]').click()
    expect(page.locator('#logpanel')).not_to_be_visible()
    expect(page.locator('.page-header .eyebrow, #page-subtitle')).to_have_count(0)
    page.locator('[data-tool="columns"]').click()
    for field in modal(page).locator('.column-item').all():
        key = field.get_attribute('data-key')
        if key in ('notes', 'profile_status'):
            field.locator('input').check()
        elif key != 'name':
            field.locator('input').uncheck()
    modal(page).locator('.modal-foot [data-i18n="save"]').click()
    page.wait_for_function("!document.querySelector('.modal-overlay')")
    page.locator('#f-search').fill('qa_001')
    note = page.locator('#rows [data-note]')
    for selector in ('[data-note]', '[data-rename]', '[data-chk]', '[data-profile-status]'):
        control = page.locator('#rows ' + selector)
        control.focus()
        page.evaluate('refreshState()')
        expect(control).to_be_focused()
    expect(note).to_have_text(page.evaluate("t('no_notes')"))
    note.dblclick()
    editor = note.locator('textarea')
    expect(editor).to_be_focused()
    draft = 'First line\n<img src=x onerror=alert(1)> second line'
    editor.fill(draft)
    page.evaluate('refreshState()')
    expect(editor).to_have_value(draft)
    screenshot(page, label + '-inline-note')
    editor.press('Control+Enter')
    expect(note.locator('textarea')).to_have_count(0)
    expect(note.locator('.note-preview')).to_have_text(draft)
    expect(note.locator('img')).to_have_count(0)
    expect(note).to_be_focused()
    page.reload(wait_until='networkidle')
    page.locator('#f-search').fill('qa_001')
    expect(note.locator('.note-preview')).to_have_text(draft)
    note.focus()
    note.press('Enter')
    note.locator('textarea').fill('Cancelled draft')
    note.locator('textarea').press('Escape')
    expect(note.locator('.note-preview')).to_have_text(draft)
    expect(note).to_be_focused()
    note.press('Enter')
    note.locator('textarea').fill('Cancelled from the save button')
    note.locator('textarea').press('Tab')
    expect(note.locator('[data-note-save]')).to_be_focused()
    note.locator('[data-note-save]').press('Escape')
    expect(note.locator('.note-preview')).to_have_text(draft)
    expect(note).to_be_focused()
    note.dblclick()
    note.locator('textarea').fill('[QA note error]')
    note.locator('textarea').press('Control+Enter')
    expect(note.locator('.note-editor-error')).to_have_text('Synthetic note save error')
    expect(note.locator('textarea')).to_have_value('[QA note error]')
    note.locator('textarea').fill('Saved after retry')
    note.locator('[data-note-save]').click()
    expect(note.locator('.note-preview')).to_have_text('Saved after retry')
    note.dblclick()
    note.locator('textarea').fill('Saved on blur')
    page.locator('#page-title').click()
    expect(note.locator('.note-preview')).to_have_text('Saved on blur')
    note.dblclick()
    note.locator('textarea').fill('')
    note.locator('textarea').press('Control+Enter')
    expect(note).to_have_text(page.evaluate("t('no_notes')"))
    for failed in (False, True):
        note.focus()
        note.press('Enter')
        note.locator('textarea').fill('Delayed response draft')
        page.evaluate("""failed=>{
            window.__qaNoteApi=api;
            api=(...args)=>args[1]==='/api/accounts/metadata'?new Promise((resolve,reject)=>{
                window.__qaCompleteNote=()=>failed?reject(new Error('Delayed note error')):
                    window.__qaNoteApi(...args).then(resolve,reject);
            }):window.__qaNoteApi(...args);
        }""", failed)
        try:
            note.locator('textarea').press('Control+Enter')
            page.locator('#f-search').click()
            page.evaluate('window.__qaCompleteNote()')
            if failed:
                expect(note.locator('.note-editor-error')).to_have_text('Delayed note error')
                expect(note.locator('textarea')).to_have_value('Delayed response draft')
            else:
                expect(note.locator('textarea')).to_have_count(0)
            expect(page.locator('#f-search')).to_be_focused()
        finally:
            page.evaluate('api=window.__qaNoteApi;delete window.__qaNoteApi;delete window.__qaCompleteNote')
        if failed:
            note.locator('[data-note-cancel]').click()
        else:
            note.press('Enter')
            note.locator('textarea').fill('')
            note.locator('textarea').press('Control+Enter')
            expect(note.locator('textarea')).to_have_count(0)
            expect(note).to_have_text(page.evaluate("t('no_notes')"))
    screenshot(page, label + '-empty-note')
    page.locator('.rail [data-tab="logs"]').click()
    expect(page.locator('#view-logs')).to_be_visible()
    expect(page.locator('#view-profiles')).not_to_be_visible()
    expect(page.locator('#page-title')).to_have_text(page.evaluate("t('monitor')"))
    expect(page.locator('#logs')).to_contain_text('Synthetic workspace connected')
    page.locator('#log-filter').fill('zz-no-log')
    expect(page.locator('#logs')).to_have_text(page.evaluate("t('no_logs')"))
    page.locator('#log-filter').fill('')
    screenshot(page, label + '-activity-log')
    page.locator('#log-clear').click()
    expect(page.locator('#log-nav-badge')).not_to_be_visible()
    page.locator('.rail [data-tab="profiles"]').click()
    page.evaluate("addLogs(['INFO Buffered while viewing profiles'])")
    page.locator('.rail [data-tab="logs"]').click()
    expect(page.locator('#logs')).to_contain_text('Buffered while viewing profiles')


def audit_customization(page, label):
    theme = page.locator('html').get_attribute('data-theme')
    accent = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--color-accent').trim().toUpperCase()")
    toggle = page.locator('#btn-sidebar-toggle')
    if page.viewport_size['width'] > 650:
        before = page.locator('.main').evaluate('el=>el.getBoundingClientRect().width')
        toggle.click()
        expect(page.locator('#workspace-sidebar')).not_to_be_visible()
        page.wait_for_function("S.preferences.folders_collapsed===true&&!document.querySelector('#btn-sidebar-toggle').disabled")
        assert page.locator('.main').evaluate('el=>el.getBoundingClientRect().width') > before
        page.reload(wait_until='networkidle')
        expect(page.locator('#workspace-sidebar')).not_to_be_visible()
        toggle.click()
        page.wait_for_function("S.preferences.folders_collapsed===false&&!document.querySelector('#btn-sidebar-toggle').disabled")
        expect(page.locator('#workspace-sidebar')).to_be_visible()
    else:
        open_navigation(page)
        expect(page.locator('#workspace-sidebar')).to_be_visible()
        close_navigation(page)
    page.locator('.rail [data-tool="browser_settings"]').click()
    expect(modal(page).locator('input[type="color"]')).to_have_count(6)
    page.evaluate("toast('Synthetic feedback\\nA second line\\nA third line','ok',0)")
    modal(page).locator('[data-color-key="accent"]').evaluate("el=>{el.value='#2e9cca';el.dispatchEvent(new Event('input',{bubbles:true}));}")
    assert page.evaluate("document.documentElement.style.getPropertyValue('--color-accent')") == '#2E9CCA'
    modal(page).locator('.modal-foot [data-i18n="cancel"]').click()
    page.wait_for_function("!document.querySelector('.modal-overlay')")
    page.locator('#toasts .toast-close').first.click()
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--color-accent').trim().toUpperCase()") == accent
    page.locator('.rail [data-tool="browser_settings"]').click()
    modal(page).locator('[data-color-key="accent"]').evaluate("el=>{el.value='#2e9cca';el.dispatchEvent(new Event('input',{bubbles:true}));}")
    modal(page).locator('.modal-foot [data-i18n="save"]').click()
    page.wait_for_function("!document.querySelector('.modal-overlay')")
    page.reload(wait_until='networkidle')
    assert page.evaluate("document.documentElement.style.getPropertyValue('--color-accent')") == '#2E9CCA'
    page.locator('.rail [data-tool="browser_settings"]').click()
    screenshot(page, label + '-custom-colors')
    modal(page).locator('[data-colors-reset]').click()
    modal(page).locator('.modal-foot [data-i18n="save"]').click()
    page.wait_for_function("!document.querySelector('.modal-overlay')")
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--color-accent').trim().toUpperCase()") == accent
    assert page.locator('html').get_attribute('data-theme') == theme


def full_flow(page, label):

    initial = page.locator('html').get_attribute('data-theme')
    page.locator('#btn-theme').click()
    expect(page.locator('html')).not_to_have_attribute('data-theme', initial)
    page.locator('#btn-theme').click()
    expect(page.locator('html')).to_have_attribute('data-theme', initial)
    language = page.locator('html').get_attribute('lang')
    open_navigation(page)
    page.locator('.sidebar [data-language]').select_option('en' if language != 'en' else 'uk')
    expect(page.locator('html')).not_to_have_attribute('lang', language)
    page.locator('.sidebar [data-language]').select_option(language)
    close_navigation(page)

    # Search, table limits and selection include hidden matching rows.
    page.locator('#f-search').fill('zz-no-match-qa')
    expect(page.locator('#no-matches')).to_be_visible()
    page.locator('#reset-filters').click()
    page.locator('#chk-all').check()
    expect(page.locator('#sel-count')).to_contain_text('50')
    page.locator('#select-everything').click()
    expect(page.locator('#sel-count')).to_contain_text('120')
    page.locator('[data-tool="bulk_edit"]').click()
    expect(modal(page).locator('[name]')).to_have_count(16)
    screenshot(page, label + '-bulk')
    close_modal(page)
    page.locator('#sel-clear').click()
    page.locator('#page-size').select_option('250')
    expect(page.locator('#rows tr')).to_have_count(120)
    page.locator('#page-size').select_option('50')
    page.locator('#profile-page-jump').fill('99')
    page.locator('#profile-page-jump').press('Enter')
    expect(page.locator('#profile-page-jump')).to_have_value('3')
    page.locator('#profile-page-jump').fill('1')
    page.locator('#profile-page-jump').press('Enter')
    row = page.locator('#rows tr').first
    row.locator('.row-options summary').click()
    bounds = row.locator('.context-menu').evaluate("el=>({top:el.getBoundingClientRect().top,bottom:el.getBoundingClientRect().bottom,height:innerHeight})")
    assert bounds['top'] >= 0 and bounds['bottom'] <= bounds['height'], bounds
    screenshot(page, label + '-menu')
    page.keyboard.press('Escape')
    # Entry and exit feedback are real UI states backed only by the fixture.
    row.locator('[data-act="login"]').click()
    expect(row.locator('.start-button .spinner')).to_be_visible()
    expect(row.locator('[data-act="close"]')).to_be_enabled(timeout=5000)
    row.locator('[data-act="close"]').click()
    expect(row.locator('.start-button .spinner')).to_be_visible()
    expect(row.locator('[data-act="login"]')).to_be_enabled(timeout=5000)
    row.locator('.proxy-check[data-act="proxy_check"]').click()
    expect(row.locator('.proxy-check .spinner')).to_be_visible()
    expect(row.locator('.proxy-check[data-act="proxy_check"]')).to_be_enabled()
    # Backend validation must remain visible and focusable after scrolling.
    row.locator('.row-options summary').click()
    row.locator('[data-act="edit"]').click()
    modal(page).locator('[name="profile_name"]').fill('[QA validation error]')
    modal(page).locator('.modal-foot [data-i18n="save"]').click()
    error = modal(page).locator('[data-error]')
    expect(error).to_contain_text('Synthetic validation error')
    expect(error).to_be_focused()
    assert error.evaluate("el=>el.getBoundingClientRect().bottom<=innerHeight")
    screenshot(page, label + '-error')
    close_modal(page)
    # A one-field form must never navigate or submit through a URL.
    open_navigation(page)
    page.locator('[data-tool="folder_create"]').click()
    field = modal(page).locator('[name="name"]')
    field.fill('QA keyboard folder')
    before = page.url
    field.press('Enter')
    page.wait_for_timeout(250)
    assert page.url == before, 'implicit form navigation'
    close_modal(page)
    if page.viewport_size['width'] <= 650:
        expect(page.locator('#btn-sidebar-toggle')).to_be_focused()
        open_navigation(page)
        expect(page.locator('.sidebar [data-language]')).to_be_visible()
        screenshot(page, label + '-navigation', embed=True)
        page.keyboard.press('Escape')
        expect(page.locator('#btn-sidebar-toggle')).to_have_attribute('aria-expanded', 'false')

    # Transfer, Dolphin and settings dialogs remain complete in every tested size.
    page.locator('.header-actions [data-tool="dolphin_import"]').click()
    expect(modal(page).locator('[name="token"]')).to_be_visible()
    modal(page).locator('details summary').click()
    expect(modal(page).locator('[name="password"]')).to_be_visible()
    screenshot(page, label + '-dolphin')
    close_modal(page)
    page.locator('.header-actions [data-tool="transfer"]').click()
    expect(modal(page).locator('.transfer-option')).to_have_count(3)
    expect(modal(page).locator('[name="settings_only"]')).not_to_be_checked()
    modal(page).locator('[name="settings_only"]').check()
    expect(modal(page).locator('[data-export-private]')).not_to_be_visible()
    modal(page).locator('[name="settings_only"]').uncheck()
    expect(modal(page).locator('[data-export-private]')).to_be_visible()
    screenshot(page, label + '-transfer')
    modal(page).locator('[data-import-package]').click()
    expect(modal(page).locator('[name="duplicates"] option')).to_have_count(2)
    audit_file_control(page)
    screenshot(page, label + '-package')
    close_modal(page)
    page.locator('[data-tool="columns"]').click()
    expect(modal(page).locator('.column-item')).to_have_count(14)
    screenshot(page, label + '-columns')
    close_modal(page)
    page.locator('.profile-management-toolbar [data-tool="browser_settings"]').click()
    expect(modal(page).locator('[name]')).to_have_count(9)
    screenshot(page, label + '-browser-settings')
    close_modal(page)

    # Existing dialogs, reports and monitoring.
    page.locator('[data-tool="history"]').click()
    expect(modal(page).locator('.history-event')).to_have_count(1)
    screenshot(page, label + '-history')
    modal(page).locator('.history-search').fill('zz-no-result')
    expect(modal(page).locator('.history-event')).to_have_count(0)
    close_modal(page)
    page.locator('[data-tool="trash"]').click()
    expect(modal(page).locator('.trash-item')).to_have_count(1)
    screenshot(page, label + '-trash')
    close_modal(page)
    row.locator('.row-options summary').click()
    row.locator('[data-act="cookies"]').click()
    expect(modal(page).locator('.cookie-json')).to_contain_text('synthetic')
    modal(page).locator('details summary').click()
    audit_file_control(page)
    screenshot(page, label + '-cookies')
    close_modal(page)
    # Retained legacy action entry; the current menu opens expanded cookie tools.
    page.evaluate("Dialogs.importCookies('qa_000')")
    audit_file_control(page)
    screenshot(page, label + '-cookie-import')
    close_modal(page)
    page.locator('.rail [data-tab="transfers"]').click()
    expect(page.locator('.job-card')).to_have_count(2)
    page.locator('[data-job-open="qa-export"]').click()
    expect(modal(page).locator('.report-table tbody tr')).to_have_count(1)
    screenshot(page, label + '-report')
    close_modal(page)
    page.locator('.rail [data-tab="workspace"]').click()
    expect(page.locator('.ops-card')).to_have_count(6)
    screenshot(page, label + '-workspace')
    page.locator('.rail [data-tab="load"]').click()
    expect(page.locator('.metric')).to_have_count(4)
    expect(page.locator('#load-chart polyline')).to_have_count(2)
    screenshot(page, label + '-monitor')
    page.locator('[data-update-open]').click()
    expect(modal(page).locator('[data-update-notes]')).to_be_visible()
    screenshot(page, label + '-updates')
    modal(page).locator('[data-update-notes]').click()
    expect(page.locator('.release-screen .fullscreen')).to_be_visible()
    screenshot(page, label + '-release')
    page.locator('.release-screen .modal-foot button').click()
    page.wait_for_function("document.querySelectorAll('.modal-overlay:not([inert])').length===1")
    close_modal(page)
    page.locator('.rail [data-tool="browser_settings"]').click()
    expect(modal(page).locator('[name="session_autosave"]')).to_be_visible()
    expect(modal(page).locator('[data-update-history]')).to_be_visible()
    screenshot(page, label + '-settings')
    modal(page).locator('[data-update-history]').click()
    expect(modal(page).locator('.release-history-item')).to_have_count(2)
    previous = modal(page).locator('[data-history-version="2026.11.23.3"]')
    previous.locator('summary').click()
    expect(previous).to_contain_text('Archived release only')
    screenshot(page, label + '-release-history')
    modal(page).locator('[data-close]').click()
    page.wait_for_function("document.querySelectorAll('.modal-overlay:not([inert])').length===1")
    close_modal(page)
    audit_notes_and_logs(page, label)


def main():
    global BASE
    OUTPUT.mkdir(exist_ok=True)
    server_log = (OUTPUT / 'fixture-server.log').open('w', encoding='utf-8')
    process = subprocess.Popen([sys.executable, str(ROOT / 'tools/visual_audit_server.py')], cwd=ROOT,
                               stdout=server_log, stderr=subprocess.STDOUT)
    BASE = 'http://127.0.0.1:18769'
    try:
        for attempt in range(50):
            try:
                reset()
                break
            except (OSError, TimeoutError):
                if process.poll() is not None or attempt == 49:
                    raise RuntimeError('Fixture server failed to start')
                time.sleep(.1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            sizes = [('desktop', 1440, 900, 1), ('laptop', 1280, 720, 1.25),
                     ('compact', 900, 650, 1.5), ('narrow', 520, 740, 2), ('short', 900, 500, 2)]
            for theme in ['dark', 'light']:
                for language in ['ru', 'en', 'uk']:
                    for size, width, height, scale in sizes:
                        label = f'{theme}-{language}-{size}'
                        errors = []
                        context = browser.new_context(viewport=dict(width=width, height=height), device_scale_factor=scale)
                        page = context.new_page()
                        page.set_default_timeout(8000)
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' and '400' not in message.text else None)
                        started = time.perf_counter()
                        try:
                            reset(theme, language)
                            page.goto(BASE, wait_until='networkidle')
                            expect(page.locator('#screen-main')).to_be_visible()
                            audit_dimensions(page)
                            screenshot(page, label + '-profiles', embed=(theme, language, size) in [('dark', 'ru', 'laptop'), ('light', 'en', 'desktop')])
                            audit_editor(page, label + '-editor', embed=(theme, language, size) == ('light', 'uk', 'narrow'),
                                         nested=(theme, language, size) == ('dark', 'ru', 'laptop'))
                            audit_customization(page, label)
                            if (theme, language, size) in [('dark', 'ru', 'laptop'), ('light', 'en', 'desktop'), ('dark', 'uk', 'narrow')]:
                                full_flow(page, label)
                            assert not errors, errors
                            RESULTS.append(dict(case=label, ok=True, scale=scale, elapsed=round(time.perf_counter()-started, 2)))
                        except Exception as error:
                            ERRORS.append(dict(case=label, error=(type(error).__name__ + ': ' + str(error).split('Aria snapshot:')[0])[:2400], console=errors))
                            try:
                                screenshot(page, label + '-FAILED', embed=len(ERRORS) <= 2)
                            except Exception:
                                pass
                        finally:
                            context.close()
            # Render a large data set; only the current page may enter the DOM.
            context = None
            try:
                reset(count=5000)
                context = browser.new_context(viewport=dict(width=1280, height=720))
                page = context.new_page()
                started = time.perf_counter()
                page.goto(BASE, wait_until='networkidle')
                expect(page.locator('#rows tr')).to_have_count(50)
                page.locator('#page-size').select_option('250')
                expect(page.locator('#rows tr')).to_have_count(250)
                page.locator('#f-search').fill('qa_4999')
                expect(page.locator('#rows tr')).to_have_count(1)
                RESULTS.append(dict(case='5000-profiles', ok=True, elapsed=round(time.perf_counter()-started, 2)))
            except Exception as error:
                ERRORS.append(dict(case='5000-profiles', error=(type(error).__name__ + ': ' + str(error).split('Aria snapshot:')[0])[:2400]))
            finally:
                if context:
                    context.close()
            # Runtime accessibility preference must remove transitions immediately.
            context = None
            try:
                reset('light', 'en')
                context = browser.new_context(viewport=dict(width=1280, height=720))
                page = context.new_page()
                page.goto(BASE, wait_until='networkidle')
                page.emulate_media(reduced_motion='reduce')
                page.locator('.header-actions [data-tool="add"]').click()
                state = modal(page).evaluate("""el=>({animation:getComputedStyle(el).animationName,
                    transition:getComputedStyle(el.querySelector('.btn')).transitionDuration})""")
                assert state == dict(animation='none', transition='0s'), state
                close_modal(page)
                page.emulate_media(reduced_motion='no-preference')
                assert page.locator('.header-actions .btn').first.evaluate("el=>getComputedStyle(el).transitionDuration") != '0s'
                RESULTS.append(dict(case='runtime-reduced-motion', ok=True))
            except Exception as error:
                ERRORS.append(dict(case='runtime-reduced-motion', error=(type(error).__name__ + ': ' + str(error).split('Aria snapshot:')[0])[:2400]))
            finally:
                if context:
                    context.close()
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)
        server_log.close()
        if ERRORS:
            print('FIXTURE_LOG_TAIL ' + (OUTPUT / 'fixture-server.log').read_text(encoding='utf-8')[-5000:], flush=True)
        report = dict(cases=RESULTS, errors=ERRORS, screenshots=[path.name for path in IMAGES])
        (OUTPUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('VISUAL_RESULT ' + json.dumps(dict(passed=len(RESULTS), failed=len(ERRORS), errors=ERRORS), ensure_ascii=False), flush=True)
    return bool(ERRORS)


if __name__ == '__main__':
    raise SystemExit(main())
