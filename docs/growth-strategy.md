# Memex Growth Strategy

## The LinkedIn Playbook — And How Memex Adapts It

LinkedIn solved the same fundamental problem Memex faces: get professionals to put
their work history into a system, then make that system searchable by the people
who pay (recruiters). Every growth decision below is informed by what worked for
LinkedIn between 2003-2008 and what killed every LinkedIn alternative since.

---

## Phase 0: The Product Is Useful Alone (Pre-Network)

**LinkedIn's insight:** LinkedIn was useful as an online rolodex before it was
useful as a hiring platform. Reid Hoffman's first move was getting 350 personal
contacts onto the platform. They used it to keep track of professional contacts —
the network effect came later.

**Memex equivalent:** Memex is already useful as a personal searchable memory.
You install it, it captures your screen, and you can search "what was I working on
last Tuesday?" This is the critical difference from every failed LinkedIn
alternative (Polywork, Braintrust, Sovrin) — they required network effects to
deliver value. Memex delivers value on day one with zero network.

**Action:** Never compromise the single-player experience to chase network
features. The personal tool IS the growth engine. Every new user should think
"this is useful for me" before they ever think about sharing.

---

## Phase 1: Auto-Start and Always-On (The Heartbeat Foundation)

### The Problem

A professional network where nodes go offline when laptops sleep is useless to
recruiters. LinkedIn profiles are available 24/7. Memex nodes need to approach
that uptime without requiring users to think about it.

### Auto-Start on Terminal Open

The install script should add a shell hook that starts the Memex daemon
automatically. This is the single highest-leverage growth action — if Memex isn't
running, it isn't capturing, and if it isn't capturing, there's nothing to share.

**Implementation:**

```bash
# Added to ~/.zshrc or ~/.bashrc by `memex install`
# Start memex daemon if not already running (silent, no output)
if command -v memex >/dev/null 2>&1; then
  memex daemon --ensure &>/dev/null &
fi
```

The `daemon --ensure` command:
1. Checks if the capture process is already running (via PID file)
2. If not, starts it in the background silently
3. If ChromaDB isn't running, starts that too
4. If the user has opted into the network (`memex publish`), starts the heartbeat
5. Returns immediately — zero delay to shell startup

On macOS, also offer a launchd plist (already exists as `com.memex.standup.plist`)
so it survives reboots without requiring a terminal to be open.

### Heartbeat and "Come Back" Emails

**The presence model** follows established protocols:

| Protocol | How It Works | Memex Analog |
|----------|-------------|--------------|
| XMPP Presence | Clients send `<presence/>` stanzas to server; server tracks online/offline/away | Node sends heartbeat to registry every 60s with current endpoint URL |
| SIP REGISTER | User agent registers with registrar server; registration expires after TTL | Node registers with registry; registration expires if no heartbeat for 5 min |
| BitTorrent DHT | Peers announce to tracker/DHT; tracker returns peer lists for a given torrent | Nodes announce skills to registry; registry returns node lists for a given query |
| mDNS/Bonjour | Devices broadcast service availability on local network via multicast DNS | Future: local network discovery for team/office memex nodes |
| IPFS DHT | Nodes announce content IDs to Kademlia DHT; other nodes query DHT to find providers | Future: fully decentralized discovery without central registry |

**Heartbeat flow:**
```
Node → Registry: POST /heartbeat
  { handle: "@joenewbry",
    url: "https://memex.digitalsurfacelabs.com",
    tags: ["kubernetes", "python", "ai-ml"],
    status: "online",
    uptime_hours: 2847,
    data_since: "2025-06-15" }

Registry stores: last_heartbeat = now()
Registry marks offline: if now() - last_heartbeat > 5 minutes
```

**Email nudges when heartbeat drops:**

If a published node goes offline for >24 hours, the registry sends a reminder:

> Subject: Your Memex node has been offline for 24 hours
>
> Hey @joenewbry — your Memex node went offline yesterday at 3:42 PM.
> While you were away, 3 recruiters searched for skills matching your profile
> (kubernetes, python) but couldn't reach your node.
>
> To get back online: open a terminal and run `memex start`
>
> Want to stay online 24/7? Run Memex on a $5/mo VPS or your Jetson.
> Guide: https://docs.memex.dev/always-on

This is directly inspired by LinkedIn's email strategy. LinkedIn sent
"X people viewed your profile this week" emails that drove massive re-engagement.
The Memex version is: "X recruiters searched for your skills but you were offline."
Same psychological trigger (professional vanity + FOMO), but honest — it's real
data from the registry's query log.

**Email cadence:**
- 24 hours offline: first nudge (if there were matching searches)
- 7 days offline: second nudge with summary ("12 searches matched your skills this week")
- 30 days offline: final nudge, then stop emailing (respect the unsubscribe)

---

## Phase 2: The Invitation Loop (LinkedIn's Core Growth Mechanic)

### How LinkedIn Did It

LinkedIn's growth from 0 to 1M users (May 2003 - August 2004) was driven by three
mechanics:

1. **Address book import** (late 2003): Upload your email contacts, LinkedIn sends
   them invitations. This was novel in 2003. It's table stakes now.

2. **Double viral loop**: Person A invites Person B. Person B joins. Person B's
   profile shows up in Person A's network. Person C sees Person A is connected to
   Person B and adds them both. Each new member increases the value for existing
   members.

3. **Professional vanity**: People WANT to have a good LinkedIn profile. It's a
   public professional identity. The "profile completeness" progress bar (introduced
   ~2005) gamified this — "your profile is 60% complete, add your education to reach
   70%." People couldn't resist filling it up.

4. **"Who viewed your profile"**: The killer engagement feature. Even free-tier
   users see that someone looked at them. Curiosity drives them back to the app.
   Premium users see who specifically. This single feature likely drove more
   re-engagement than anything else LinkedIn built.

### Memex Invitation Loop

The Memex equivalent isn't "invite your contacts" — it's **"invite your collaborators."**

When Memex detects that you've been working on a project with someone (their name
appears in your screen captures — Slack messages, PR reviews, shared docs), it can
suggest:

> "You've collaborated with @janedoe on 47 occasions in the last month.
> If Jane runs Memex too, recruiters searching for Kubernetes teams will find
> both of you — and your collaboration is verifiable proof of teamwork."
>
> [Invite Jane to Memex] [Not now]

This is more powerful than LinkedIn's address book import because it's based on
**actual collaboration evidence**, not just "you have their email." And the value
proposition is concrete: "your teamwork becomes visible proof."

**The invitation flow:**

```
1. You install Memex → captures your work → useful on its own
2. You publish to the network (`memex publish`) → discoverable by recruiters
3. Memex detects collaborators in your screen data
4. You send them an invite: "I use Memex to track my work — here's proof we
   worked together on [project]. Want to make that visible?"
5. They install Memex → their data corroborates yours
6. Cross-referencing strengthens both profiles' trust scores
```

### The Memex Profile Completeness Equivalent

LinkedIn's progress bar drove profile completion. Memex's equivalent is a
**"coverage score"** — how completely your work history is captured:

```
Your Memex Coverage Score: 73%

[========--------] 73%

What's missing:
  + You have gaps on weekends (expected if you don't work weekends)
  + No data from Jan 12-15 (laptop was off?)
  + Your Kubernetes work is well-documented (847 captures)
  + Your Python work has thin coverage (only 23 captures in last month)

To improve: Keep Memex running. The daemon auto-starts with your terminal.
```

This drives the "always on" behavior we need without being coercive. It's
gamification of data depth, which directly maps to how useful the node is to
recruiters.

### "Who Searched For Your Skills"

The Memex equivalent of "who viewed your profile":

> This week on the Memex network:
> - 8 searches matched your skills (kubernetes, python, ai-ml)
> - 3 recruiters queried your node directly
> - Your most-searched skill: kubernetes (5 of 8 searches)
> - You were offline for 12 hours and missed 2 potential matches
>
> [View full audit log] [Upgrade to always-on]

This creates the same professional vanity / FOMO loop that drives LinkedIn
engagement, but with real data. You know exactly what people searched for and
whether your node was available.

---

## Phase 3: Beachhead Markets (Where To Start)

### LinkedIn's Approach

LinkedIn started with Silicon Valley tech workers — Reid Hoffman's personal
network. People who were already comfortable with online profiles, who changed
jobs frequently, and who valued network effects. Only after saturating this
beachhead did they expand to other industries.

### Memex Beachhead: People Who Are Already Angry at Resumes

From the GTM analysis (see `gtm/screen-trust-beachheads.csv`), the highest-urgency
niches share a trait: **they have a trust problem that resumes can't solve.**

**Tier 1 beachheads (launch with these):**

| Niche | Size | Why They're Urgent | Invitation Loop |
|-------|------|-------------------|-----------------|
| **Toptal rejects** | 5-8K/yr | Failed a gatekeeping test; need alternative proof | "Toptal said no — your screen history says yes" |
| **#OpenToWork devs on X** | 50K+/mo | Job hunting RIGHT NOW, need to stand out | Share memex link alongside resume on X |
| **Self-taught / bootcamp grads** | 200K+/yr | Zero credentials, pure trust problem | Screen history IS the credential |
| **OSS maintainers seeking sponsors** | 3-5K | Sponsors can see commits but not invisible work | "Your commit graph shows 10% of your work" |
| **Freelancers on Upwork** | 12M+ | Clients can't verify hours or quality | Provable work sessions replace time tracking |

**Why these specific groups:**
1. They're already online and vocal (easy to find and reach)
2. They have immediate, painful need (not theoretical)
3. They're on X/Reddit/HN where word-of-mouth spreads fast
4. They don't need to be sold on the concept — they already wish this existed
5. They will invite collaborators because corroboration strengthens their case

**Tier 2 (expand after 1K nodes):**
- Fractional CTOs proving hours to clients
- DAO contributors claiming compensation
- AI/prompt engineers proving they actually use AI daily
- Indie game devs showing publishers their velocity

**Tier 3 (expand after 10K nodes):**
- General software engineers job hunting
- Freelance designers proving process (not AI-generated)
- Remote workers fighting RTO mandates with productivity evidence

---

## Phase 4: The Recruiter Side (Monetization and Sybil Prevention)

### LinkedIn's Monetization Arc

LinkedIn was free for 2+ years before monetizing. They reached 1M users (Aug 2004)
before launching premium subscriptions (2005). Recruiter tools came after that.

The order matters: **fill the supply side first, then charge the demand side.**

### Memex Recruiter Access Tiers

| Tier | Cost | Access | Sybil Prevention |
|------|------|--------|-----------------|
| **Explorer** | Free | Browse registry, see who's online, see skill tags | Email verification + rate limit (5 searches/day) |
| **Recruiter** | $29/mo | Query online nodes directly, see search results, get offline notifications | Stripe payment = identity verification |
| **Enterprise** | $99/mo | API access, query fan-out to multiple nodes, analytics, saved searches | Company domain verification + payment |

**Why charge at all (even $29/mo):**

The payment isn't primarily about revenue — it's a **sybil filter**. A real
recruiter won't blink at $29/mo. A scraper, a competitor running reconnaissance,
or a bad actor fishing for proprietary information will. The credit card on file
is identity verification that Stripe has already solved.

This is similar to how LinkedIn gates InMail behind Premium. The cost filters out
noise and makes the messages that do come through more credible.

**Income/identity verification options considered:**

| Approach | Friction | Sybil Resistance | Chosen? |
|----------|----------|-------------------|---------|
| Email-only | Very low | Very low (disposable emails) | Explorer tier only |
| Stripe payment | Low | High (credit card = real identity) | Yes — Recruiter tier |
| LinkedIn OAuth | Medium | High (established professional identity) | Future — adds trust signal |
| Company domain verification | Medium | Very high (company email) | Yes — Enterprise tier |
| Government ID (Stripe Identity) | High | Maximum | Overkill for now |

---

## Phase 5: The Central Registry (Yes, You Need It)

### Why Centralized Discovery Is Correct for Now

Every successful decentralized network started with centralized discovery:

- **BitTorrent**: Started with centralized trackers. DHT came years later (BEP 5,
  2008). Trackers are still used alongside DHT today.
- **IPFS**: Uses bootstrap nodes (centralized servers that help new nodes find the
  DHT). Without them, you can't join the network.
- **Matrix**: Requires a homeserver. matrix.org is the de facto central server that
  most users connect through.
- **Mastodon**: mastodon.social is the dominant instance. "Decentralized" in
  architecture, concentrated in practice.
- **DNS itself**: Centralized root servers, decentralized resolution.

**The pattern**: centralized bootstrap → prove the concept works → decentralize
when scale demands it.

The registry (`registry.memex.dev`) should be:
- **Open source**: Anyone can run their own registry
- **Lightweight**: FastAPI + SQLite, deployable on a $5 VPS or Fly.io
- **Metadata only**: Handle, tags, endpoint URL, heartbeat, online status
- **Replaceable**: If the registry dies, nodes still function locally. Another
  registry can be spun up and nodes re-register.

### Registry Tracks Available Nodes (Not IP Addresses)

The registry doesn't need raw IP addresses. It stores the node's public endpoint
URL (Cloudflare tunnel, ngrok URL, or VPS hostname). The presence model:

```
ONLINE:  heartbeat within last 5 minutes, endpoint responding
AWAY:    heartbeat within last 30 minutes, endpoint may be stale
OFFLINE: no heartbeat for 30+ minutes
GHOST:   no heartbeat for 7+ days (hidden from search, email nudge sent)
```

This is the same model as XMPP presence (online/away/xa/offline) adapted for a
network of MCP endpoints instead of chat clients.

### Universal Searchability

For everyone to be searchable, we need two layers:

**Layer 1: Tag-based discovery (always available, even when node is offline)**
```
Recruiter: "find me kubernetes engineers"
Registry:  returns all nodes tagged with "kubernetes"
           - @joenewbry (online, 2847 hours of data, Kubernetes + Python + AI/ML)
           - @janedoe (away, 1200 hours, Kubernetes + Terraform)
           - @bobsmith (offline, last seen 3h ago, Kubernetes + Go)
```

**Layer 2: Vector-based discovery (available 24/7 via remote vector store)**

This is the vector approach you mentioned. DP-noised vectors uploaded to a
centralized vector store enable semantic search even when nodes are offline:

```
Recruiter: "engineer who debugged Istio service mesh issues and wrote Helm charts"
Vector store: cosine similarity search across all uploaded vectors
              returns document IDs + similarity scores + owner node handles
Registry:     resolves handles to endpoints
Recruiter:    queries online nodes for full (filtered) results
```

The vectors provide 24/7 **discoverability**. The live node provides on-demand
**detail**. This two-layer model means:
- Offline nodes are still findable (vectors are in the remote store)
- Online nodes give richer results (direct MCP queries)
- Recruiters can bookmark offline nodes and get notified when they come online

---

## Phase 6: The Viral Mechanics (Compounding Growth)

### LinkedIn's Network Effect Formula

LinkedIn's growth was exponential because each new member made the network more
valuable for everyone:

```
Value of network = f(nodes) * f(connections between nodes)
```

LinkedIn's genius was creating multiple viral loops:
1. **Invitation loop**: You invite contacts → they join → they invite their contacts
2. **Vanity loop**: You see who viewed you → you come back → you update profile
3. **SEO loop**: Public profiles rank in Google → people find LinkedIn → they join
4. **Endorsement loop**: Someone endorses you → you get notified → you endorse back

### Memex Viral Loops

**Loop 1: The Collaboration Loop**
```
You run Memex → you publish to network → recruiter finds you → recruiter also
queries your detected collaborators → collaborators install Memex → more nodes
→ more recruiter searches → more installs
```

**Loop 2: The FOMO Loop**
```
Your node is online → recruiter queries it → you see the audit log → you tell
colleagues "recruiters are searching my Memex" → colleagues install Memex
```

**Loop 3: The Coverage Loop**
```
You see your coverage score → you keep Memex running to fill gaps → more data
→ better search results → more recruiter satisfaction → more recruiter queries
→ more email notifications to other nodes → more people keep Memex running
```

**Loop 4: The Cross-Reference Loop**
```
You and a colleague both run Memex → recruiter searches for "team that shipped
X" → finds both of you → corroboration increases trust → recruiter pays →
team members invite more teammates → entire team is on Memex
```

**Loop 5: The Public Proof Loop (LinkedIn SEO equivalent)**
```
You share your Memex link on X/LinkedIn/resume → "Verified work history:
memex.dev/@joenewbry" → people click it → see what Memex is → install it
themselves
```

---

## Phase 7: Growth Milestones and Metrics

### LinkedIn's Timeline

| Date | Users | Milestone |
|------|-------|-----------|
| May 2003 | 0 | Launch (Reid's 350 contacts) |
| Aug 2004 | 1M | Address book import working |
| 2005 | 4M | Launched premium subscriptions |
| Apr 2007 | 10M | Recruiter tools gaining traction |
| 2008 | 33M | International expansion |

### Memex Target Timeline

| Milestone | Target | Trigger |
|-----------|--------|---------|
| **10 nodes** | Month 1 | Personal network — friends and colleagues who will test it |
| **100 nodes** | Month 3 | Beachhead outreach — Toptal rejects, #OpenToWork, OSS maintainers |
| **500 nodes** | Month 6 | Word of mouth + HN/Reddit/X posts. Registry is live. First recruiter signups. |
| **1,000 nodes** | Month 9 | Recruiter tier launches ($29/mo). Cross-reference and endorsement features. |
| **5,000 nodes** | Month 15 | Enterprise tier. API access. First paying companies. |
| **10,000 nodes** | Month 24 | Vector store enables 24/7 discovery. DHT exploration begins. |

### Key Metrics to Track

| Metric | What It Measures | Target |
|--------|-----------------|--------|
| **DAU/MAU ratio** | How many installed nodes are actually running | >60% |
| **Uptime per node** | Average hours/day a published node is online | >12h/day |
| **Heartbeat coverage** | % of published nodes that heartbeated in last 24h | >80% |
| **Searches per day** | Registry search volume (demand signal) | Growing week-over-week |
| **Query-to-install rate** | How many recruiter queries lead to new node installs | >5% |
| **Invitation acceptance** | % of collaboration invites that convert to installs | >20% |
| **Email re-engagement** | % of "you were offline" emails that bring node back | >15% |

---

## Implementation Priority (What to Build, In Order)

### Now (Weeks 1-4)
1. **`memex daemon --ensure`** command for shell auto-start hook
2. **Shell hook installer** in `memex install` that adds the auto-start line
3. **launchd plist** for macOS login-item auto-start (backup for non-terminal users)
4. **Registry MVP** — FastAPI + SQLite, /register, /heartbeat, /search, /node
5. **`memex publish`** command — registers with registry, starts heartbeat

### Next (Weeks 5-8)
6. **`memex discover`** command — search the registry from CLI
7. **Email capture on registration** — for nudge emails
8. **Heartbeat monitoring + email nudges** — "you were offline, X searches matched"
9. **Coverage score** — show users their capture completeness
10. **Collaborator detection** — scan screen data for repeated names/handles

### Then (Weeks 9-16)
11. **Recruiter signup + Stripe** — $29/mo tier with identity verification
12. **Registry web UI** — search nodes by skills in a browser
13. **Vector export pipeline** — DP-noised vectors to centralized store
14. **"Who searched your skills" weekly digest** — the LinkedIn killer feature
15. **Public profile pages** — memex.dev/@handle (SEO loop)

### Later (Months 5+)
16. **Invitation system** — "invite your collaborators"
17. **Endorsement system** — nodes vouch for each other
18. **Enterprise tier** — API access, bulk queries, analytics
19. **Mobile companion** — view audit log, see who searched you
20. **DHT exploration** — decentralize discovery for 10K+ nodes

---

## The Pitch at Each Stage

**To the individual (install phase):**
"Never forget what you worked on. Search your entire screen history locally."

**To the job seeker (publish phase):**
"Stop writing resumes. Let recruiters search your actual work."

**To the collaborator (invite phase):**
"Your teammate runs Memex. Recruiters can verify you worked together."

**To the recruiter (monetization phase):**
"Search verified work histories instead of reading embellished resumes. $29/mo."

**To the enterprise (scale phase):**
"Access a network of verified engineers. Query their actual work history via API."

---

## Why This Beats LinkedIn (Long-Term)

| Dimension | LinkedIn | Memex Network |
|-----------|----------|---------------|
| Data source | Self-reported claims | Timestamped screen captures |
| Verification | "Trust me" | "Check my work" |
| Data ownership | LinkedIn owns it | You own it, on your machine |
| Privacy | LinkedIn sells your data | Guard model + audit log |
| Cost to user | Free (you are the product) | Free (you own the infra) |
| Network bootstrap | Address book import | Single-player utility first |
| Viral loop | Vanity + invitations | Collaboration evidence + FOMO |
| Recruiter signal | Keyword matching on profiles | Semantic search on actual work |

LinkedIn won because it was the first professional network with real network
effects. Memex doesn't need to replace LinkedIn's social graph. It needs to
replace LinkedIn's **signal quality**. The pitch isn't "leave LinkedIn" — it's
"your LinkedIn says you know Kubernetes; your Memex proves it."

---

## Risk Factors

| Risk | Mitigation |
|------|-----------|
| People won't run always-on software | Auto-start + coverage score gamification + email nudges |
| Employers will ban screen recording | Guard model ensures no proprietary data leaks; frame as personal tool |
| Recruiters won't pay for a new tool | Start free, prove signal quality, then charge. LinkedIn took 2 years. |
| Fake data / gaming | Temporal consistency + cross-referencing + volume makes faking impractical |
| Registry becomes single point of failure | Open source + self-hostable + metadata only (easy to rebuild) |
| Privacy incident kills trust | Guard model + audit log + DP noise on vectors. But: one bad leak is fatal. |
| LinkedIn copies the feature | They can't — their architecture is centralized. Data sovereignty is structural. |

---

## Summary

The growth strategy follows LinkedIn's proven playbook adapted for a decentralized
architecture:

1. **Be useful alone** (personal search tool) — LinkedIn was a rolodex before a network
2. **Auto-start everything** (daemon + heartbeat) — LinkedIn made profile creation frictionless
3. **Gamify completeness** (coverage score) — LinkedIn's progress bar drove profile completion
4. **Create FOMO** (who searched your skills) — LinkedIn's "who viewed your profile"
5. **Enable invitations** (collaborator detection) — LinkedIn's address book import
6. **Start with a beachhead** (angry resume haters) — LinkedIn started with Silicon Valley tech
7. **Charge the demand side** (recruiter tiers) — LinkedIn charged recruiters, not candidates
8. **Centralize discovery, decentralize data** — like DNS: central root, distributed resolution

The central registry is correct and necessary for now. It's a phone book, not a
database. Keep it dumb, keep it open source, and evolve toward DHT when you have
10K+ nodes and the engineering bandwidth to justify it.
