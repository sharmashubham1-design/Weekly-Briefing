SAMPLE = {
  "headline": "A guided tour of how a Monday Briefing works",
  "tldr": ["This is sample teaching content—not current news.", "Live mode researches the previous Monday–Sunday window.", "Your feedback, tutoring, and quiz results shape the next edition."],
  "movers": [{"name":"Example institution","kind":"Demo only","what_happened":"In live mode, this space summarises sourced public remarks, disclosures and major market moves.","takeaway":"Treat disclosures as backward-looking evidence, not instructions.","sources":[]}],
  "items": [
    {"topic":"Markets & investing","title":"Reading a market move without chasing it","summary":"A price move can reflect new information, positioning, liquidity, or all three.","why_it_matters":"Separating observation from explanation reduces overconfidence.","concept":"Market liquidity: how readily an asset can trade without moving its price.","sources":[]},
    {"topic":"Real estate & mortgages","title":"Why mortgage rates and home prices can diverge","summary":"Financing costs affect affordability, while supply and local demand also shape prices.","why_it_matters":"A national average can hide the conditions in a specific market.","concept":"Affordability combines price, borrowing cost, income, taxes, insurance and maintenance.","sources":[]},
    {"topic":"Tech, AI & industry","title":"From AI demo to durable economics","summary":"A useful product still needs reliable performance, distribution and sustainable unit economics.","why_it_matters":"Adoption headlines do not by themselves show who captures value.","concept":"Unit economics measures revenue and variable cost at the customer or transaction level.","sources":[]}
  ],
  "trends": [{"trend":"No live trend in demo mode","evidence":"Demo mode intentionally contains no current claims.","confidence":"Certain","caveat":"Generate with an API key to research the week."}],
  "concepts": [
    {"topic":"Markets & investing","term":"Disclosure lag","definition":"The time between an investment position date and when it becomes public.","example":"A 13F filing may describe holdings from weeks earlier."},
    {"topic":"Real estate & mortgages","term":"Debt service","definition":"The cash required to make principal and interest payments.","example":"A higher rate can raise monthly debt service even at the same home price."},
    {"topic":"Tech, AI & industry","term":"Unit economics","definition":"The revenue and variable costs associated with one unit of business.","example":"An AI service compares subscription revenue with inference and support cost."},
    {"topic":"Markets & investing","term":"Base rate","definition":"How often something occurs before considering case-specific evidence.","example":"Compare a dramatic story with the historical frequency of similar outcomes."}
  ],
  "decision_lens": [{"knowledge_point":"Translate a headline into variables you can monitor.","questions_to_ask":["What is confirmed versus inferred?","What evidence would change the interpretation?","Which costs, risks, or time lags are missing?"]}],
  "quiz": [
    {"topic":"Markets & investing","concept":"Disclosure lag","q":"Why should a 13F filing be treated as backward-looking?","options":["It reports positions after the measurement date","It predicts next quarter’s returns","It includes every asset globally"],"answer_index":0,"explanation":"A filing becomes public after its portfolio measurement date, so positions may have changed."},
    {"topic":"Real estate & mortgages","concept":"Debt service","q":"What can increase monthly debt service on the same-priced home?","options":["A lower borrowing rate","A higher borrowing rate","More housing supply alone"],"answer_index":1,"explanation":"Holding other terms constant, a higher rate raises the payment needed to service the loan."},
    {"topic":"Tech, AI & industry","concept":"Unit economics","q":"Which cost is most relevant to AI product unit economics?","options":["Variable inference cost per user","A competitor’s logo colour","The age of the founder"],"answer_index":0,"explanation":"Inference usage is a variable delivery cost and directly affects contribution economics."},
    {"topic":"Markets & investing","concept":"Base rate","q":"What does a base rate provide?","options":["A guaranteed outcome","A historical starting probability","A price target"],"answer_index":1,"explanation":"Base rates anchor judgment in how often comparable outcomes occurred before case-specific evidence."},
    {"topic":"Real estate & mortgages","concept":"Affordability","q":"Which belongs in a full affordability check?","options":["Only listing price","Price, financing and ownership costs","Only national inventory"],"answer_index":1,"explanation":"Affordability includes the purchase price, financing, income, taxes, insurance and upkeep."},
    {"topic":"Tech, AI & industry","concept":"Value capture","q":"Why doesn’t adoption alone prove durable value capture?","options":["Usage can grow while margins or pricing stay weak","Adoption is never measurable","Revenue is unrelated to products"],"answer_index":0,"explanation":"A product can grow usage without defensible pricing, margins or distribution."}
  ]
}
