"""The flows a first-time rider hits: plan a trip, switch Modes, choose a ride, plan a crawl."""
import re

from playwright.sync_api import expect


def open_home(page, base_url):
    page.goto(base_url + "/")
    expect(page.locator("#places [data-place]").first).to_be_visible()


def plan_to(page, place):
    page.click(f'#places [data-place="{place}"]')
    expect(page.locator("#view-results")).to_be_visible()
    expect(page.locator("#results .opt").first).to_be_visible(timeout=15_000)


def test_home_page_loads(page, base_url):
    open_home(page, base_url)
    expect(page).to_have_title(re.compile("Hopper"))
    expect(page.locator("#cta")).to_have_text("See trips")
    expect(page.locator("#modes [data-mode]")).to_have_count(4)


def test_plan_a_trip_from_a_popular_place(page, base_url):
    open_home(page, base_url)
    plan_to(page, "oracle_park")
    expect(page.locator("#r-title")).to_contain_text("Oracle Park")
    assert page.locator("#results .opt").count() >= 3
    expect(page.locator("#results .opt.active .opt-price")).to_contain_text(re.compile(r"Free|\$\d"))
    expect(page.locator("#trace")).to_contain_text("Ranker")


def test_switching_mode_reranks_without_replanning(page, base_url):
    open_home(page, base_url)
    plan_to(page, "golden_gate_park")
    plans = []
    page.on("request", lambda r: plans.append(r.url) if r.url.endswith("/api/plan") else None)
    page.click('#modes-r [data-mode="broke"]')
    expect(page.locator("#results .opt").first).to_contain_text("Broke")
    assert plans == [], "a Mode switch should only re-rank cached trips"


def test_choose_a_ride(page, base_url):
    open_home(page, base_url)
    plan_to(page, "oracle_park")
    combo = page.locator("#results .opt", has_text="Walk + Ride").first
    if not combo.count():
        combo = page.locator("#results .opt", has=page.locator(".seg.ride")).first
    combo.locator(".opt-head").click()
    expect(page.locator("#cta")).to_have_text("Choose a ride")
    page.click("#cta")
    expect(page.locator("#modal li[data-ride]").first).to_be_visible()
    assert page.locator("#modal li[data-ride]").count() >= 3
    expect(page.locator("#ride-confirm")).to_contain_text(re.compile(r"Confirm .+ about \$\d"))


def test_bar_crawl_needs_21_plus_then_plans(page, base_url):
    open_home(page, base_url)
    page.click('#modes [data-mode="barcrawl"]')
    expect(page.locator("#cta")).to_have_text("Plan my crawl")
    page.click("#cta")
    expect(page.locator("#error")).to_contain_text("21")
    page.check("#c-age")
    page.click("#cta")
    expect(page.locator("#r-title")).to_contain_text(re.compile(r"\d bars from"), timeout=15_000)
    assert page.locator("#results .stop h3").count() >= 2
    expect(page.locator("#cta")).to_contain_text(re.compile(r"Book ride home|Start the crawl"))


def test_phone_width_has_no_sideways_scroll(page, base_url):
    page.set_viewport_size({"width": 375, "height": 812})
    open_home(page, base_url)
    assert page.evaluate("document.documentElement.scrollWidth") <= 375
    plan_to(page, "chase_center")
    assert page.evaluate("document.documentElement.scrollWidth") <= 375


def test_csp_tripwire_fires(page, base_url):
    # Proves the per-test CSP check can fail: a script from an unlisted host must be blocked.
    open_home(page, base_url)
    page.evaluate("""() => { const s = document.createElement("script");
                             s.src = "https://cdn.example.invalid/x.js"; document.head.appendChild(s); }""")
    page.wait_for_function("window.__csp.length > 0")
    assert "script-src" in page.evaluate("window.__csp[0]")
    page.evaluate("window.__csp = []")
