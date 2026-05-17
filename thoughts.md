# General thoughts and ideas

String of consiousness thoughts to improve [bold.org](http://bold.org) site for user trust, polish and general growth opportunitites

## Browsing provided links on site

- The home page has a picture of MacOS on a Microsoft Surface
- A lot of flashing and motion can translate to slight distrust (e.g. live indicator and $ counter) - have these been tested?
- Blogs like [https://bold.org/blog/best-physical-therapy-schools](https://bold.org/blog/best-physical-therapy-schools/)
  - "Notorious" typically has a negative conotation. Famous criminals are notorious.
  - Try removing the numerous links to other sites (like school pages) from blogs to help keep viewers on the page and increase conversion
  - Hypothesis: people viewing the blogs are not ready to start applying. Too early in the life cycle. Maybe we can adapt to meet them when they're ready by doing something like providing custom weekly or monthly emails reminding them we're here for when they're ready (e.g. new scholarships you might like)
  - Alternative hypothesis: maybe the CTA and next steps could be oriented around getting them over that hump of starting to apply. Starting can be the hardest part (e.g. get 5 applications out in 5 minutes).
  - Test removing the large square CTA box at the start of the blog, maybe that drives a lot of people away
  - Ultimately: who are the visitors? LLMs? Parents?

## Data analysis

- Page type funnel
  - Blogs are the obvious stand out opportunity. High views but 0.5% submit rate when the other two types of pages are about 15% (that's a 30x difference!)
- Device split
  - Mobile organic sessions are notably lower on mobile vs desktop, some cases half
  - Interestingly, mobile organic sessions are are higher on mobile for blogs
  - Submit rate on mobile is notably lower than desktop. Roughly 8% vs 5% organic google sessions vs form complete sessions
- Top public landing pages
  - The be bold scholarship is the top converter
  - Again, blogs have a near-zero conversion rate
  - Persona-targeted SGPs can convert much higher than generic SGPs (nursing and black scholarships are much higher than merit based or easy scholarships)
    - NOTE: this tells me understanding who the users are and targeting each cohort with scholarships for them (among other things) is key. For example: scholarships for software engineers, older students, low GPA, you name it.
  - There is a routing problem because a number of the highest organic pages do not convert, but lower ones do. Maybe we could have an agent that optimizes flows to route people from the pages that get views to contexual ones that do convert.
- Tech index signals
  - llms.txt status is 404. Looks like a bug to fix and help LLM traffic
  - No real issues here otherwise
- Event santity
  - donor_registration and donor_registration2 might be duplicates (have same event value) possibly causing some data issues. They have the same values.
  - account_created is larger than session_start. If I understand the events, this shouldn't be possible and is indicative of a data issue where account_created is firing false positives or session start_start is not firing in some instances. Maybe ID tracking issues (e.g. cross-domain)
  - The click event doesn't make sense with such a small number. Could be an old event or underfiring or intentionally too narrow and could use a rename
  - Either clickhouse or GA4 is duplicate counting. This is because the ratios all are around 0.5 of the other (0.4 to 0.6). Clickhouse is likely source of truth, GA4 is not trustworthy.
  - For some reason GA4 catches 60% of blog but 40% of the other pages - possible indicator of something being different with the blog page tracking.
- Experiment summary
  - The SGP by year pages redesign test is not showing a real difference in the numbers. 
  - Can't be sure because it is NOT stat sig yet. Depending on how long this has run for, I'd keep it running. If it has been going on for multiple weeks I'd call it quits.

## Identified opportunities

- Blog → SGP Routing Agent (recurring loop)
  - Weekly job that reads each blog post, picks the most relevant SGP/scholarship-detail page, and generates a contextual CTA (headline + body + link). Each week it also reviews how the previously deployed CTAs performed (CTA click-through, blog → SGP flow, downstream submits), keeps the winners, rewrites the underperformers, retires CTAs that never convert, and adds CTAs for new or recently changed blogs. Targets the 30x conversion gap between blogs (about 0.5%) and scholarship pages (about 15%).
- New Persona SGP Generator (recurring loop)
  - Weekly job that scans demographic analytics, new blog posts, GSC search demand, and emerging scholarship trends to spot underserved personas (e.g. scholarships for software engineers, older students, low-GPA students, single parents) and spin up brand-new persona-specific SGPs, drafting the full page (title, hero copy, intro, FAQ, target keyword, URL slug) and queuing it for review and indexing. Each week it also reviews how previously launched persona SGPs are performing, refines underperformers, ships new ones for trending personas, and retires any that consistently fail to attract traffic or convert. Justified by persona pages converting way better than generic ones: nursing 46% and Black students 71% vs about 8% on merit-based or easy-scholarship pages.
- Search engine results page (SERP) CTR Optimizer (recurring loop)
  - Weekly job that finds pages whose GSC CTR is far below the expected CTR for their position (e.g. `/scholarships`, flagship No-Essay, `/blog/what-gpa-do-you-need-to-get-a-full-scholarship`), generates 3–5 title+meta variants per page, and queues them for review or A/B test.
- Instrumentation Watchdog (event-triggered)
  - Detects impossible event relationships (`account_created > session_start`), near-identical event-pair counts (`donor_registration` vs `donor_registration2`), and GA4↔ClickHouse drift, then posts plain-English Slack alerts. Acts as the trust substrate for every other agent and directly feeds Part 3's fake-wins work.
- Experiment Auto-Call Agent (recurring loop)
  - Reads live experiment results (e.g. the flat By-Year Pages Redesign Test at 9.71% vs 9.70%) and figures out, given the traffic so far, the smallest lift the test could realistically detect and how long it would take to reach a confident answer. Recommends stop / keep running / escalate, with a one-line rationale (e.g. "stop, needs 14 more weeks to detect a 5% lift, current traffic too low").
- Mobile Form Drop-off Fixer (recurring loop)
  - Mobile users start the signup form at roughly the same rate as desktop but complete it at about half the rate. The agent watches per-field abandonment, proposes mobile-only fixes (fewer fields, autofill, sticky CTA, progressive disclosure, larger tap targets), and queues mobile-only A/B tests to close the gap.
- Lifecycle Re-engagement Agent (recurring loop)
  - Most blog and SGP visitors are too early in the funnel to apply now. The agent segments captured emails by behavior (bounced from a blog, browsed an SGP but didn't submit, submitted but never verified, etc.) and sends personalized weekly or monthly emails ("new scholarships you might like", "5 quick scholarships you can apply to in 5 minutes") with subject-line and send-time experiments to bring them back when they're ready.
- Blog Page Layout & Trust Optimizer (recurring loop)
  - Separate from rewriting blog copy. This agent tweaks the page itself (layout, removing or downgrading outbound links that pull users off-site, restyling or repositioning the CTA, choosing better images, simplifying the hero, hiding low-value sidebars) to keep readers focused and feeling trusting. Runs as small layout-level A/B tests on the highest-traffic blogs (e.g. `/blog/best-physical-therapy-schools`, `/blog/what-gpa-do-you-need-to-get-a-full-scholarship`).
- ChatGPT App for Bold (one-shot generator)
  - Ship a small "ChatGPT App" on OpenAI's Apps SDK (note: this is OpenAI's user-facing in-chat app surface, which happens to use the MCP protocol under the hood, not a traditional developer-tool MCP server). The app has just a few focused capabilities (find scholarships I'm eligible for, surface deadlines for a given category, save / apply via Bold), kept intentionally narrow. The point isn't heavy direct usage; it's that being a published, indexed app in ChatGPT (and similar AI assistants) makes Bold dramatically more likely to be mentioned and cited when *any* user asks ChatGPT scholarship questions. Treat it as SEO for the LLM era: brand presence in the AI discovery layer.
- llms.txt Generator (one-shot generator)
  - Reads the sitemap, classifies pages by surface and topic, and generates a structured `llms.txt` (currently 404) so AI assistants (ChatGPT, Perplexity, AI Overviews) can crawl and cite Bold accurately.

