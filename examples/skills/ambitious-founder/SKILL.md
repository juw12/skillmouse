---
name: ambitious-founder
description: Two jobs in one. (1) Select any task or prompt and get an ambition pass - the goal beyond the goal, what the field's best expert would do from the raw data, which other fields to borrow from, what outside judge proves it worked - plus a rewritten, copy-ready prompt. (2) Select a business or product idea and get a founder pressure-test - a four-lens board (Offers, Monopoly, Product, Make), unit economics with the formulas shown, a small simulated buyer panel, a verdict and the cheapest real test to run this week. Use for "/be-ambitious", "/founder", "aim higher", "go deeper", "what would a top expert do", "test my business idea", "would people buy this", "is this profitable".
---

# Ambitious Founder (SkillMouse edition)

Combines **be-ambitious** (RoboNuggets, MIT; built on Felix Rieseberg's article *How to be more
ambitious: a tutorial for humans with models*) and **founder-skill** (Jake Schincariol, MIT).
In SkillMouse you can't run scripts, search the web or launch sub-agents, so you do everything in one
answer and **label what is estimated or simulated**. The full version with the Python tools
(buyer-panel bookkeeping, Van Westendorp pricing, unit-economics model, computed plan verdict) is
`skills/ambitious-founder` in github.com/juw12/skills.

## Rules (never break)

1. **Better, not bigger.** Raise the outcome, the standard or the perspectives. Never just add features or deliverables.
2. **Do what the expert does, not how they talk.** Name their real methods and instruments. Vocabulary alone is role play.
3. **An outside judge decides.** Never grade your own work. Always name the test, measurement or real buyer that would prove it.
4. **Hard target, honest report.** Treat the ambitious target as reasonable; a missed target with real numbers beats a faked pass.
5. **No invented facts.** No made-up competitors, prices, market sizes or budgets. Missing input = list it as missing.
6. **Lenses, not people.** Write "the Offers lens", never "Hormozi says". Never quote or speak as the authors.
7. **Simulated buyers are not customers.** The buy rate is an upper bound. Never use panel lines as testimonials.

## Pick the mode from the input

- A **task or prompt** (fix, build, write, analyse, "rewrite this prompt") -> **Mode A**.
- A **business or product idea** (what it sells, to whom, at what price) -> **Mode B**.
- Unclear -> Mode A, and say Mode B is available if it's an idea.

## Mode A - ambition pass

Use only the types that fit (usually one or two):

- **Altitude** - what should happen next? Ladder of three rungs: (1) understand, don't just fill in; (2) get to the decisions; (3) replace the ritual with a durable system. If a rung has no outside judge, step down.
- **Depth** - answer: what would a top professional do that wasn't asked; the rawest material they'd start from; the exact methods and tools; what (not you, not the user) would show it's right. Set an unreasonable target and treat it as reasonable.
- **Range** - turn the nouns into verbs ("a deck" -> "getting busy people to decide in 30 minutes"), then name the crew: field -> the job they'd actually do -> their method or tool.

Output, sized to the input:

1. Goal beyond the goal - one line.
2. Types that fit (and the ones skipped) - one line each.
3. The plan for each type.
4. What it needs - data, tools, access, each marked *have* / *missing*.
5. **Rewritten prompt** in one fenced block, written the way the user would type it, ending with the outside judge and what counts as a pass.
6. Next - the highest rung that can be done and checked with the access available now.

## Mode B - founder pressure-test

If the product, customer or price is missing, ask for them in one short message and stop.

1. **Ambition line** - the goal beyond the goal for this business, and the real-world test that would prove it (pre-orders, paid pilots, a waitlist with a price).
2. **Board** - apply each lens from `lenses.md` separately (Make lens only for physical products). For each: score 1-10, vote FUND / FUND IF / PASS, the top risk that would kill it, one condition. Then the vote tally, the risks raised by more than one lens, and the strongest version of the business (say so if it differs from the pitch).
3. **Unit economics** - show each formula with the user's numbers:
   - contribution per unit = price - variable cost per unit (materials, packaging, shipping, fees, ads per sale, returns)
   - break-even units per month = fixed monthly costs / contribution
   - months to pay back = startup cost / (monthly contribution - fixed costs)
   - for hardware: landed unit cost = BOM + assembly + test + packaging + freight + duty + yield loss; tooling, certification and the first MOQ batch are startup cash.
   Mark every number as *user-given* or *estimate*. If an input is missing, list it instead of guessing.
4. **Quick panel** - 8-10 one-line reactions from clearly different buyers (segment, budget, habit, main doubt). Don't be agreeable: most people don't buy most things. Tally "N buy / M pass", group the pass reasons, note what would flip a no. Label it **simulated - upper bound**.
5. **Verdict** in words - *looks viable* / *not yet* / *missing data* - with the numbers that decide it.
6. **This week** - the cheapest real test, with its success line written before it runs (e.g. "30 pre-orders in 14 days at $35").

End with one line of honest limits: lens votes are framework applications, panel answers are simulated,
numbers marked *estimate* need real quotes. Not financial, legal or tax advice.
