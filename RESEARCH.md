# Research

Full findings from research rounds, with sources. `NOTES.md` holds the short takeaways that feed planning.

Upkeep:
- Research agents return their reports and the main session saves them here. Parallel agents don't write to this file directly, so their edits can't overwrite each other.
- Newest round first. Each round: date, question, findings, sources, caveats.
- Tags: [E] study or published data, [M] manufacturer claim, [R] user reviews or press, [I] our inference.
- Compress old rounds every few months: keep findings that still drive decisions and their sources, drop the rest.

## 2026-11-17: Gameplay loop and retention (3 agents)

Question: what keeps kids coming back to a hygiene device over weeks, how to coach young kids by audio, how to design rewards, and which data rules apply in the US and Texas.

### A. Comparable kids' products

Products:
- **Philips Sonicare for Kids:** kids brush to feed and customize "Sparkly", a pet in the app, with multiple profiles. Kids played with Sparkly so long that bedtime slipped, so Philips made Sparkly get tired after a session ([Techlicious](http://www.techlicious.com/blog/philips-sonicare-for-kids-electric-toothbrush-app-sparkly/), [Mental Floss](https://www.mentalfloss.com/technology/toothbrushing-app-was-reprogrammed-be-less-addictive)). [M] "98% of surveyed parents" report longer brushing ([Philips](https://www.usa.philips.com/c-p/HX6321_02/sonicare-for-kids-sonic-electric-toothbrush)). [R] Novelty wore off "within a few brushing sessions" for one reviewer, Bluetooth sync complaints, a child upset when a bug broke their streak ([Live Science](https://www.livescience.com/philips-sonicare-for-kids-review), [Looria](https://looria.com/review/philips-sonicare-for-kids)).
- **Oral-B Disney Magic Timer:** a 2-minute timer reveals a picture, and each session earns a sticker. Scanning Oral-B/Crest products unlocks sticker books. [M] "9 in 10 kids brush longer", from P&G's own 2014 study of 52 children ([BusinessWire](https://businesswire.com/news/home/20140303005964/en/Oral-B%c2%ae-Launches-Interactive-Oral-Care-App-Kids)).
- **GUM Playbrush:** a sensor brush controls phone games, 4 free and 9 by subscription. [M] A 6-week study funded by Playbrush (103 children aged 6 to 10): 72% vs 56% likelihood of brushing twice a day ([brochure](https://cdn.shopify.com/s/files/1/0088/4185/5031/files/GUM_Playbrush_Scientific_brochure_EN.pdf)).
- **Colgate Magik:** augmented-reality monster game plus a parent dashboard. [R] The app freezes when small hands cover the sensors, and it misreads where the child brushed ([PCMag](https://webcf.waybackmachine.org/web/20220603233611/https://www.pcmag.com/reviews/colgate-magik)).
- **Grush:** games plus a parent app, and data can be shared with a dentist. Needs a tablet in the bathroom. [R] Calibration failures ([Irish Times](https://www.irishtimes.com/business/technology/tech-tools-review-grush-gaming-toothbrush-1.2566189)).
- **hum by Colgate, UK school program:** a weekly class dashboard for teachers, with class comparisons and challenges ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12357393/)).
  - [E] 409 children aged 8 to 11. 29% never connected the brush.
  - [E] Of those who did, 55% used it for more than 2 months.
  - [E] Twice-daily brushing on 48% of recorded days, with weekends worst.
  - [E] Parents reported brushing that the device missed in 24% of paired comparisons.
  - Barriers: phone and Wi-Fi, syncing, charging, kids distracted by the phone, parents feeling monitored.
- **Day care sink trial, closest to our device** (2024 cluster trial, ages 3 to 6, 162 children): a sensor at the sink triggers a tablet animation that ends with dancing animals ([Sci Rep](https://www.nature.com/articles/s41598-024-56233-9)).
  - [E] Soaping time rose 62% (8.5 s to 13.8 s) and held for all 4 weeks.
  - [E] Two weeks after removal it was only 1.2 s above baseline. Washing frequency did not change.
  - The authors suggest rotating the rewards.
- **Other handwashing products:**
  - SureWash: camera-based technique training for hospitals. No kids' sink device found.
  - Light-up timers and dispensers (Time Timer WASH, 20-second timers). [R] One teacher said kids would rather sing or count than watch a light.
  - "A Germ's Journey" (book, song, glo-gel). [E] Better handwashing in a classroom RCT ([PLOS ONE](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7682880/)).
- **Routine devices:**
  - Joon: a parent app assigns chores and the child's app grows a pet. Rewards wait for parent approval, about $90 a year. It only works if parents stay involved ([Common Sense](https://www.commonsensemedia.org/app-reviews/joon-kids-chore-list-chart)).
  - Hatch Rest: color cues kids can follow without reading.
  - Yoto: screen-free physical cards a child can use alone.

Retention evidence:
- [E] 8-week Sonicare trial with toddlers: brushing frequency fell week by week in every arm, including the control. Lottery rewards beat fixed rewards: 6.0 vs 3.9 sessions per week ([PLOS ONE](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0236692)).
- [E] Brush Up pilot (ages 5 to 6): brushing time 40 s to 109 s at 14 days. A year later, without the app, the gains were not significant ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC6709707)).
- [E] A gamified app RCT improved knowledge, not brushing frequency. Only 44% of kids were satisfied with its novelty ([BMC Oral Health](https://link.springer.com/article/10.1186/s12903-025-07575-x)).
- [E] A review of 9 trials (weeks to 3 months): novelty fades. It recommends refreshed content and parent involvement, which is untested ([Frontiers](https://www.frontiersin.org/journals/dental-medicine/articles/10.3389/fdmed.2025.1639572/full)).
- [E] An 18-week adolescent trial: app use dropped, with no hygiene effect ([ResearchGate](https://www.researchgate.net/publication/338986928)).

Gaps found:
- Nearly every connected toothbrush shows rewards only on a phone. Exceptions: physical stickers, Hatch lights, Yoto cards, and the day care trial's fixed tablet.
- No product found shows long-term progress on the device itself.
- No kids' handwashing device with a progression loop across washes.
- No independent long-term data for Sonicare, Playbrush, Grush or Magik.
- No study comparing parent apps with progress shown on the device.

### B. Coaching and rewards (child development research)

Coaching:
- **Scaffolding.** Wood, Bruner & Ross 1976: add help when the child struggles, remove it when they succeed. A preregistered replication reportedly found no effect, so treat it as a principle ([Hendrick](https://carlhendrick.substack.com/p/we-need-to-talk-about-scaffolding)).
- **Expertise reversal** (Kalyuga 2007): guidance that helps novices hurts experts. Judge expertise from the first step the learner takes unaided ([PDF](https://www.uky.edu/~gmswan3/EDC608/Kalyuga2007_Article_ExpertiseReversalEffectAndItsI.pdf)).
- **Prompting** (Libby 2008, small studies of children with autism): least-to-most prompting was fastest for most children. A constant time delay (wait 3 to 5 s, then prompt) was as effective and more efficient ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC2846579)).
- **Working memory** (Gathercole 2008, ages 5 to 6): children reliably fail longer spoken instructions, so use one step per instruction ([preprint](https://eprints.whiterose.ac.uk/id/eprint/91941/8/WM%20in%20spoken%20instructionsPrePrint.pdf)).
- **Feedback** (Kluger & DeNisi 1996): d = 0.41 on average, but it lowered performance in over a third of cases, worse when it points at the self rather than the task.
- **Praise.**
  - Positive feedback raises intrinsic motivation (d about 0.33, Deci 1999).
  - Generic praise ("good drawer") made 4-year-olds more helpless after mistakes than specific praise (Cimpian 2007).
  - Praise should be sincere, about the process, and about something the child controls (Henderlong & Lepper 2002, [PubMed](https://pubmed.ncbi.nlm.nih.gov/12206194/)).
- **False corrections:** preschoolers stop trusting sources that were wrong before (Koenig & Harris 2005, not re-verified). Alarm research shows the same "cry wolf" drop.

Rewards:
- **Lepper, Greene & Nisbett 1973:** preschoolers who expected an award drew about half as much later. Unexpected awards had no effect.
- **Deci, Koestner & Ryan 1999** (128 studies): expected, tangible, performance-contingent rewards undermined motivation (d about -0.28 to -0.40), more strongly in children. This applies to tasks already found interesting, which handwashing mostly isn't ([PDF](https://depts.washington.edu/techdocs/papers/deciExtrinsicRewardsAndIntrinsicMotivation99.pdf)).
- **Vegetable trials (Cooke, Wardle):** stickers or praise for 12 days raised liking, which held at 3 months. Praise worked almost as well as stickers ([BPS](https://www.bps.org.uk/research-digest/bribing-kids-eat-their-greens-really-does-work)).
- **Streaks:** no peer-reviewed study in young children. The concerns come from commentary. In adults, one missed day did not hurt habit formation (Lally).
- **Group rewards:** the Good Behavior Game (team-based classroom reward) has strong evidence: single-case Tau-U 0.82, group designs d about 0.50, smaller in RCTs.

Habits:
- Lally 2010: median 66 days to automaticity (range 18 to 254). Singh 2024 review: medians 59 to 66 days, individual range 4 to 335. Early repetitions give the biggest gains.

Handwashing studies:
- [E] **Bangladesh nudges** (Dreibelbis 2016): painted paths and footprints from toilet to sink, no messaging. Handwashing with soap went 4% to 68% the next day and 74% at 6 weeks. The effect held at 5 months in an RCT ([LSHTM](https://researchonline.lshtm.ac.uk/id/eprint/3055240), [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4730520)).
- [E] **Philippines cluster RCT (IDinsight):** nudges added 17 to 26 percentage points at under $70 per school. More than 75% were still in place at 4 months. They only worked where there was water ([IDinsight](https://www.idinsight.org/article/a-nudge-toward-hand-hygiene-simple-design-features-improved-handwashing-among-filipino-students/)).
- [E] Group handwashing at school did not lead kids to wash on their own (Duijster, Philippines).
- [E] **Song study** (2026, 4 classrooms, 47 children): median wash time at day 29 was 22 s with a song vs 5 s with spoken instruction. Median step score 2 vs 1 out of 9, so young children do very few steps ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41707914/)).
- [R] **Pepe robot** (Kerala, one school): handwashing up about 40%. Press-release data.
- **Candy trial** (ages 3 to 6): tests whether removing a sink reward undermines washing. Results not published yet ([protocol](https://pmc.ncbi.nlm.nih.gov/articles/PMC9873181/)).

Caveats: several figures come from abstracts or summaries (the replication, Pepe, the song study).

### C. US and Texas data rules (design planning, not legal advice)

Statute texts read: CUBI 503.001, TDPSA 541.001/.002, SCOPE Act, Educ. 26.009 and 29.022, Penal 21.15, 26 TAC 746.3417, Hum. Res. 42.04271. From law-firm summaries only: COPPA school authorization, Ch. 32 deletion rule, litigation status. Not checked: 45 CFR 1303 (Head Start).

Rules:
- **Penal Code 21.15:** a crime to record or transmit an image of someone in a bathroom without consent and with intent to invade privacy. A Pi streaming frames to a laptop is "transmitting" ([text](https://texas.public.law/statutes/tex._penal_code_section_21.15)).
- **COPPA 2025 amendments** ([Fed. Reg.](https://www.govinfo.gov/content/pkg/FR-2025-04-22/html/2025-05904.htm)): compliance due since April 22, 2026. Applies if the device or app is online and aimed at children.
  - "Personal information" now includes biometric identifiers that can recognize a person, and photos or video of a child.
  - Requires a written security program (312.8) and a published retention policy (312.10).
  - Third-party sharing needs separate consent.
  - The audio exception (use once, delete) covers voice only.
  - School consent for parents: educational use only, per the [FTC FAQ](https://www.ftc.gov/business-guidance/resources/complying-coppa-frequently-asked-questions), not in the rule.
- **CUBI, Bus. & Com. Code 503.001** ([text](https://statutes.capitol.texas.gov/Docs/BC/htm/BC.503.htm)).
  - "Biometric identifier" includes a "record of hand or face geometry" and doesn't require identification.
  - Commercial capture needs notice and consent (the parent's, for a child). No sale. Destroy within 1 year after the purpose ends. Up to $25,000 per violation.
  - HB 149 (from Jan 1, 2026) exempts AI development and training unless the system identifies people. Untested.
- **TDPSA, ch. 541:** small businesses exempt, but they still need consent to sell sensitive data. "Biometric data" must identify a person and excludes video-derived data, so landmarks are likely out. A known child's data counts as sensitive.
- **SCOPE Act (HB 18):** only for services with social features (profiles plus content others see). A parent dashboard is likely outside it. Partly blocked in court.
- **App Store Accountability Act (SB 2420):** in effect since July 2026. A parent app in the app stores must handle the store's age and consent signals. A web app avoids it ([FPF](https://fpf.org/blog/comparing-enacted-app-store-accountability-acts/)).
- **School-only rules** (deferred with the school version):
  - FERPA: public schools only. The vendor acts as a "school official" under district control.
  - Educ. Code ch. 32 Subch. D: no ads, profiling or sale, and deletion within 60 days of a request.
  - TEA 32.1021: parental consent before apps.
  - Educ. 26.009: written parental consent before videotaping a child.
  - PPRA: no marketing use.
- **Childcare:** 26 TAC 746.3417 requires handwashing before meals and water play, and after toileting or diapering, outdoor time, sand play and animals. No camera rule found.

Design implications, most important first:
1. Process frames on the device with the camera, and never stream or save images. Prefer sinks outside restrooms.
2. No video or landmark storage in deployed builds (`landmarks.npz` and `frames.jsonl` are for team testing only).
3. Store only derived wash records, with a named deletion period.
4. Parent consent flow (COPPA plus CUBI notice) that describes the camera and landmarks.
5. Written security program and retention policy. No ads, no sale, no analytics SDKs.
6. Adult-only parent accounts, no child logins or social features.
7. Training data from children needs separate, explicit consent.
8. School version: class totals by default, small groups hidden.

Open questions for a lawyer or advisor:
- Do 21 landmarks per frame count as a CUBI "record of hand geometry"? Does the HB 149 AI exemption cover a deployed product?
- Does a stream inside the device count as "transmitting" under 21.15?
- Does a fully offline device trigger COPPA at all?
- Is the team an "operator" or a "small business"? Does UT's involvement change that?
- Can a private daycare consent for parents? (school version)
