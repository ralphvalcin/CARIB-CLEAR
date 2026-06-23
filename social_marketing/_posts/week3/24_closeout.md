# Post 24 — Aug 7

**Platform:** X (thread, 6 posts)  
**Title:** What I learned building a fintech infrastructure solo in 21 days  
**Status:** Draft

---

## Thread Content

**1/6**
21 days. One developer. Three codebases. One system. No team.

Here's what I learned:

**2/6**
**AI tools let you build above your weight class.**

I'm not a fintech engineer. I'm a QA/SDET with 4 years in AI healthcare. But with Hermes Agent and Claude Code, I built a matching engine, a netting system, a compliance agent, voice pipeline, and credit scoring — in 21 days.

The tools don't replace judgment. They remove the typing bottleneck.

**3/6**
**Governance mattered more than algorithms.**

I spent more time on the approval queue, the audit trail, the HITL escalation rules than on any matching algorithm. When your system moves money, correctness matters more than speed.

The SqliteApprovalQueue (leases, idempotency, metrics) is the most important component I built.

**4/6**
**The abstraction layer is the moat.**

MultiRailBroker with one interface covering Stellar, ACH, and Mobile Money means adding a new rail is 30 minutes of code. Adding a new jurisdiction is configuration.

The interface is the moat, not the implementation.

**5/6**
**Voice-first is not a gimmick.**

Haiti's literacy rate is ~61%. Mobile penetration is over 80%. The user who needs this the most cannot fill out a web form.

Building the voice pipeline in Kreyol wasn't a feature. It was the whole point.

**6/6**
**Building in public works.**

Posting every day forced me to explain my decisions. Explaining them forced me to think clearly. I caught design flaws in my head before they hit the code because I had to write them down for you.

If you're building something hard, do it in public. The accountability is real.

That's the thread. CARIB-CLEAR ships today. On to the next.

#CARIB_CLEAR #FutureCaribbean #Buildathon #BuildingInPublic #LessonsLearned

---

## Review Notes
- [ ] This is the closing statement — every word counts
- [ ] Post 5 about Haiti voice-first — does it hit hard enough?
- [ ] Post 6 about building in public — good meta reflection?
- [ ] Ready to post after submission day?