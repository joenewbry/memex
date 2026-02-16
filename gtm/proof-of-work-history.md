# History of Proof of Work for Knowledge Workers

Research compiled Feb 15, 2026. Context: positioning Memex (screen history as a verifiable trust layer) — what's been tried before and where the open lane is.

---

## Timeline

### The Idea (1945)
- **Vannevar Bush's Memex** — "As We May Think", The Atlantic, July 1945. Proposed a desk-sized device storing all of a person's books, records, and communications, retrievable by association. The original Memex was about augmenting memory; the trust/verification layer was never imagined.
- Source: https://www.theatlantic.com/magazine/archive/1945/07/as-we-may-think/303881/

### Lifelogging Research (2001–2010)
- **Gordon Bell's MyLifeBits** (2001) — Microsoft Research project where Bell digitized his entire life: emails, phone calls, photos, web browsing, screen activity. Published *Total Recall* (2009). Proved the concept technically but never found a commercial use case beyond "because you can."
  - Source: https://en.wikipedia.org/wiki/MyLifeBits
- **Microsoft SenseCam** (2003) — Wearable camera that auto-captured photos based on sensors. Academic research tool, never broadly commercialized. Found genuine use helping dementia patients remember their day.
  - Source: https://en.wikipedia.org/wiki/Microsoft_SenseCam

### Freelance Screenshot Verification (2003–2015)
- **oDesk** (2003) — Founded by Tsatalos & Karamanlakis. Pioneered screenshot-based time tracking for remote freelancers. Random screenshots every 10 minutes + keystroke/mouse activity levels. **Closest historical precedent** to Memex's mechanism, but framed as surveillance, not empowerment.
- **Elance** (1998, merged 2013) — Older platform, merged with oDesk in 2013, rebranded as **Upwork** in 2015.
- **Upwork Work Diary** — Still the core billing mechanism for hourly contracts. 6 screenshots/hour + activity meters. BuzzFeed reported workers found it deeply invasive — "like being watched by your boss every second."
  - **Key insight: same tech, but framing as surveillance created resentment rather than trust.**
  - Sources: https://en.wikipedia.org/wiki/Upwork, https://www.buzzfeednews.com/article/carolineodonovan/upwork-freelancers-work-diary-keystrokes-screenshot

### Passive Time Tracking (2006–2013)
- **RescueTime** (2006–2007) — Founded in Seattle. Runs in background, logs time per app/website. Productivity analytics, not verification. ~2M users at peak. Still alive but small.
  - Source: https://www.cbinsights.com/company/rescuetime
- **WakaTime** (2013) — Developer-specific automatic time tracking via IDE plugins. Tracks time per language, project, file. 500K+ active developers. TechCrunch called it "Fitbit for developers." Half their users are NOT contractors — devs like seeing their own data. Closest to a "credential" angle but never marketed it that way.
  - Source: https://techcrunch.com/2015/09/22/wakatime-fitbit-for-developers/

### Employee Monitoring / Bossware (2012–2020)
- **Hubstaff** (2012) — Screenshots + GPS for remote teams. Customers include Instacart, Groupon, Ring. Bootstrapped.
- **Time Doctor** (2012) — Screenshots + productivity scoring. 83K customers including Allstate, Verizon.
- **Teramind** (2014) — Screen recording + user behavior analytics for enterprises. Raised $6M.
- **ActivTrak** (2009, grew 2019+) — $70M Series B. Used by 6,500+ orgs including universities and governments.
- **COVID boom** (2020) — The "bossware boom." Time Doctor pageviews tripled. Category exploded. Market now ~$5B+ globally.
  - **Pattern: every one is employer → employee surveillance. Workers hate it. Adopted because managers demand it, not because workers want it.**
  - Source: https://www.businessofbusiness.com/articles/employee-monitoring-software-productivity-activtrak-hubstaff-covid/

### Exam Proctoring (2008–2020)
- **ProctorU** (2008) — Live human + AI proctoring. 11.7% market share.
- **Examity** (2013) — AI-powered proctoring. 13.5% market share.
- **Respondus LockDown Browser** — Browser lockdown + webcam recording.
- Market: $894M in 2024, projected $2.5B by 2033. Screen recording as proof someone did work honestly. Students hate it — same surveillance framing.
  - Source: https://www.globalgrowthinsights.com/market-reports/online-exam-proctoring-market-101994

### Screen History as Memory / AI (2022–2025)
- **Rewind.ai** (2022) — Founded by Dan Siroker (ex-Optimizely CEO). macOS app recording screen continuously, searchable via AI. "Mind-boggling compression" — 10GB → 3MB. a16z backed. Pivoted to **Limitless** in 2024 (AI pendant for conversations). Acquired by Meta late 2025. Mac app shutting down. Proved the tech works at consumer scale but pivoted away before finding PMF as a trust tool.
  - Sources: https://techcrunch.com/2024/04/17/a16z-backed-rewind-pivots-to-build-ai-powered-pendant-to-record-your-conversations/, https://9to5mac.com/2025/12/05/rewind-limitless-meta-acquisition/
- **Microsoft Recall** (2024) — Windows feature that screenshots every 5 seconds, searchable via AI. Only on Copilot+ PCs with NPUs. Privacy backlash delayed launch. Framed as personal memory, not trust.
  - Source: https://support.microsoft.com/en-us/windows/retrace-your-steps-with-recall-aa03f8a0-a78b-4b3e-b0a1-2eb8ac48701c
- **Windrecorder** — Open source alternative to Recall/Rewind. https://github.com/yuka-friends/Windrecorder
- **OpenRecall** — Privacy-first open source alternative. https://github.com/openrecall/openrecall

### Blockchain Credentials (2018–present)
- **Velocity Network** — Blockchain-based credential verification for employment history.
  - Source: https://www.computerworld.com/article/1613987/coming-soon-a-resume-validating-blockchain-network-for-job-seekers.html
- **Proof-of-Skill Protocol** — Academic paper on blockchain verification of skills/work history.
  - Source: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5150993
- Various Web3 attempts at on-chain work verification. None got traction — the problem isn't verification of claims, it's generating the evidence in the first place.

---

## Competitive Landscape Map

| Framing | Examples | Problem |
|---------|----------|---------|
| **Surveillance** (employer watches worker) | Upwork, Hubstaff, Time Doctor, ActivTrak | Workers hate it. Adopted top-down, not bottom-up |
| **Proctoring** (institution watches test-taker) | ProctorU, Examity | Same — subjects resent it |
| **Personal memory** (search your own past) | Rewind, Recall, MyLifeBits | No trust/credential layer. Just memory augmentation |
| **Activity metrics** (time per app/project) | RescueTime, WakaTime | Aggregated stats, not verifiable process evidence |
| **Blockchain claims** (verify stated credentials) | Velocity, Proof-of-Skill | Verifies claims but doesn't generate the underlying evidence |

## The Open Lane

Nobody has built screen history as a **user-owned trust credential** that the worker controls and chooses to share.

- **Worker-owned** (not employer-installed)
- **Opt-in sharing** (not surveillance)
- **Evidence generation** (not just claim verification)
- **Process proof** (not just output proof)

The closest precedent is WakaTime (developers voluntarily tracking coding for personal insight) but they never turned it into a shareable trust signal. The Upwork Work Diary proves the mechanism *works* for trust, but the surveillance framing means workers adopt it grudgingly.

## Key Lessons from History

1. **Framing is everything.** Same technology (screen recording), opposite reception depending on who controls it and why.
2. **Rewind proved demand exists** for personal screen history — then pivoted away. Meta bought the team, not the product.
3. **The bossware market is $5B+** proving employers will pay for verification. The question is whether workers will adopt it voluntarily when it benefits them.
4. **WakaTime's surprise**: half of users are non-contractors who track coding for personal satisfaction. People *want* to see their own work data.
5. **Blockchain credentials failed** because they verify claims but don't generate evidence. The hard part isn't verification — it's capture.
6. **The PayPal/eBay analogy holds**: Upwork built screenshot verification for its marketplace. Memex can be the screenshot verification layer that works across all marketplaces, owned by the worker.
