# Website Brief: TransitPulse first pass (paratransit direction)

Supersedes the earlier hub/mismatch-demo brief. Target: live on a real domain by 23 July, final polish 24 July, so it supports the YC application submitted 25 July and the cold outreach running this week.

## 1. What this site is for

Two audiences, in priority order:

1. **Cold outreach recipients.** A paratransit ops manager who gets Arya's email will look us up. The site's job is to make two students look like a credible company in under 30 seconds.
2. **YC readers.** They will click the URL in the application. Same job.

It is NOT a self-serve product demo. Paratransit trips are door-to-door and involve protected health information; there is no public "try it on your agency" map. The demo lives in screenshots and a short video on the site, and in live walkthroughs on calls.

## 2. Positioning (use this framing everywhere)

Paratransit and NEMT operators run on opaque legacy dispatch software (Ecolane, TripSpark, RouteMatch). Nobody can see why the system scheduled a trip the way it did. That makes ADA compliance reporting painful, makes bad routing impossible to challenge, and makes operators distrust their own tools. TransitPulse predicts demand and schedules trips with a full audit trail: every routing decision comes with a human-readable explanation.

One-liner: "Scheduling your dispatchers can actually trust. Every trip, explained."

## 3. Pages (single-page site plus one subpage is fine)

1. **Home**
   - Hero: one-liner above, subhead: "Demand prediction and trip scheduling for paratransit and NEMT operators, with a plain-English audit trail for every routing decision."
   - CTA: "Book a 15-minute call" (Calendly or mailto, no forms infrastructure)
   - Problem section: three short blocks (opaque dispatch decisions, compliance reporting burden, demand you can't see coming)
   - Product section: 3 or 4 screenshots or a 60-90s video. Source material: the existing dashboard, the SHAP explainability output restyled as "why this trip" cards, the demand prediction view. Synthetic trip data only, no real rider info anywhere.
   - Evidence strip: 0.94 R2 demand model (temporal validation), 1.16% mean routing optimality gap, SHAP explainability benchmarked vs ARIMA and deep learning, Grand Final of a 13,000-student engineering competition. One line each, link nothing to EWB branding; the competition is a credential, not the identity.
   - Team: two founders, one photo each, one line each.
   - Footer: contact email, that's all.
2. **/method** (optional if time): how the model works, honest limitations. Skeptical ops managers read this. Can ship after the 25th.

## 4. Build notes

- Stack: whatever is fastest for you. A single React + Vite page or even plain Astro/HTML is fine, this is a marketing site not an app. Reuse dashboard components only where they save time.
- Repo: build in `web/` in this repo.
- Deploy: Vercel, Day 1, iterate on the live URL. Domain: transitpulse.* (Arya registers, decide .com/.io/.co by availability).
- Design: clean and boring beats flashy. Light background, one accent color, Inter or system font, real product screenshots. No stock photos, no map hero, no LED/FPGA imagery on the product site.
- Screenshots: Arya delivers restyled "why this trip" explanation cards and a demand view on synthetic paratransit-shaped data by evening of 21 July. Until then use placeholder boxes.
- OG image and favicon matter here: outreach recipients will see the link unfurl in email clients and LinkedIn.

## 5. Out of scope

Auth, payments, blogs, CMS, interactive demos, pricing page (pricing is "book a call" at this stage), anything Ladywood/Birmingham/EWB-branded in the product UI.

## 6. Definition of done (23 July)

- Live on the real domain with SSL
- Hero, problem, product (screenshots or video), evidence, team, CTA all present
- Loads fast, looks fine on a phone (outreach replies get read on phones)
- OG preview renders correctly when the URL is pasted into an email or LinkedIn
