# Legal review: face recognition and number plate recognition

Edition 1, November 2026. Applies to one site running the HSS Security Surveillance System.

## 1. Status of this document

This review was prepared by the project team for the site owner (the data controller) and its legal counsel. It sets out how the face and number plate features work, which Nigerian laws apply, the risks, and the conditions the site commits to before the features are switched on.

It is not legal advice. A qualified legal practitioner must read it, check it against the law as it stands on the day, and give a written opinion before the features are unlocked. Section numbers of laws are given as a guide; counsel confirms them.

The software keeps face and plate recognition locked until an administrator has read this document to the end, recorded the legal opinion and the data protection impact assessment, and accepted every condition in section 14. The acceptance is recorded in the audit log with this document's version, expires after 12 months, and can be withdrawn at any time, which locks the features again.

## 2. What the features do

**Face recognition.** The server finds faces in camera video, checks that each face is clear enough (size, angle, sharpness), turns it into a numeric template (a biometric template), and compares the template with the templates of people on a watchlist. When a face matches a watchlist entry above a set threshold, the system raises an alert with a cropped image for a person to review. Faces that do not match are discarded straight away; their templates are not stored.

**Number plate recognition.** The server finds vehicles, reads their plates (Nigerian format, for example ABC123DE), and compares each plate with a plate watchlist. Matches raise alerts. Plate reads may be kept for a short period so that a vehicle's arrival and departure can be checked during an incident.

**What the system does not do.** It does not connect to government databases (NIMC, FRSC, state vehicle registries or police systems). It does not guess age, sex, ethnicity, emotion or any other characteristic. It does not make any decision about a person by itself; every match goes to a human.

**Trial stages.** Stage 1 (camera suitability) only counts faces and plates and checks their quality; it identifies no one and is allowed without this review. Stages 2 to 4 (enrolment, matching on live cameras, then go-live) identify people and need this review accepted.

## 3. Personal data involved

| Data | Category | Why it matters |
|---|---|---|
| Face images in video and snapshots | Personal data | Already collected by ordinary CCTV |
| Face templates of watchlist members | Sensitive personal data (biometric) | Uniquely identifies a person |
| Face templates of passers-by | Sensitive personal data (biometric), transient | Created for every face seen, even if discarded in seconds |
| Plate numbers | Personal data | Can be linked to the owner or driver |
| Time and place of each match or read | Personal data | Shows a person's or vehicle's movements |
| Watchlist reasons and notes | Personal data, possibly about offences | Can affect a person's access, job or reputation |

Biometric data used to identify a person is sensitive personal data under the Nigeria Data Protection Act 2023. Every face in view is processed to make a template, so face recognition processes the biometric data of everyone who walks past an enabled camera, not only of people on the watchlist.

## 4. Laws and rules that apply

- **Constitution of the Federal Republic of Nigeria 1999, section 37**: the right to privacy of citizens, their homes, correspondence, telephone conversations and telegraphic communications. Any monitoring must be justified and proportionate.
- **Nigeria Data Protection Act 2023 (NDPA)** and the **Nigeria Data Protection Commission (NDPC)** it created. Key parts: the principles of processing (lawfulness, fairness, transparency, purpose limitation, data minimisation, accuracy, storage limitation, security and accountability, around section 24); lawful bases (section 25); sensitive personal data (section 30); data protection impact assessments (section 28); data protection officers (section 32); data subjects' rights, including the right not to be subject to decisions based solely on automated processing (sections 34 to 38); security (section 39); breach notification to the NDPC within 72 hours (section 40); transfers outside Nigeria (sections 41 to 43); registration of data controllers of major importance (section 44); penalties (section 48).
- **NDPC General Application and Implementation Directive (GAID) 2025**, which explains how the NDPA is applied, including impact assessments, compliance audit returns and the duties of data controllers of major importance. Counsel confirms which provisions apply to this site.
- **Labour law and employment contracts**, where staff are monitored. Staff must be told; collective agreements may require consultation with unions or staff representatives.
- **Criminal procedure and police requests**: sharing matches or footage with the police must follow a written request and be recorded.
- **Any sector rules** that bind the site owner (for example rules for financial institutions, oil and gas facilities or public bodies) and the site owner's own contracts with clients and landlords.

## 5. Lawful basis

Counsel must record one lawful basis for each purpose.

- **Plate recognition** for site security: most likely the site owner's legitimate interests in protecting people and property, provided a balancing test shows those interests are not overridden by drivers' rights. The balancing test is part of the impact assessment.
- **Face recognition**: biometric data is sensitive, so a legitimate interest alone is not enough. One of the section 30 conditions must also apply. Possible conditions are explicit consent (practical for staff who enrol for access, not for visitors or the public), the establishment, exercise or defence of legal claims, or a substantial public interest set out in law. If counsel cannot identify a condition that fits each group of people (staff, contractors, visitors, the public), face recognition must not be used for that group.

The purpose is limited to the security of the site: preventing and detecting crime, unauthorised entry and safety incidents. The data must not be used for attendance, performance management, marketing or any other purpose without a new review.

## 6. Necessity and proportionality

The impact assessment must show that less intrusive measures (guards, access cards, ordinary CCTV, camera AI that detects people without identifying them) are not enough for the risks the site faces. The system is designed to keep the intrusion small:

- Recognition runs only on cameras that have been qualified one by one (entrances, gates, vehicle lanes), never on every camera, and never in toilets, changing rooms, prayer rooms, clinics or rest areas.
- Matching is against a watchlist only. The system never builds a record of everyone who passed.
- Non-matching face templates are discarded immediately.
- A person reviews every match before anyone acts on it.

## 7. Data protection impact assessment (DPIA)

A DPIA is required before go-live because the processing uses new technology, biometric data and systematic monitoring of a publicly accessible area. It must cover at least:

1. A description of the processing and its purposes (this document, section 2).
2. The lawful basis and section 30 condition for each group of people.
3. Necessity and proportionality (section 6).
4. The risks to people: wrongful identification, discrimination through unequal accuracy, chilling effect, data breach, misuse by staff, function creep.
5. The measures that reduce each risk (sections 8 to 12) and the risk that remains.
6. The views of the data protection officer and, where suitable, of staff representatives.
7. Whether prior consultation with the NDPC is needed because high risk remains.

The DPIA is reviewed at least once a year and whenever cameras, watchlist rules or purposes change.

## 8. Transparency and signs

People must know before they enter the recognition area.

- Signs at every entrance and vehicle gate, readable from a distance, before the first enabled camera. Suggested wording: "CCTV with face and number plate recognition is in operation for the security of this site. Operated by [site owner]. Contact the Data Protection Officer: [contact]. Full notice at reception and at [web address]."
- A full privacy notice at reception and on the site owner's website: the purposes, lawful basis, what is kept and for how long, who it is shared with, people's rights and how to use them.
- Staff and contractors are told in writing before go-live, and the notice is added to staff policies.

## 9. Watchlist rules

The watchlist is the main source of risk. The site adopts these rules:

- **Who may be listed**: people barred from the site by a documented decision (for example after theft or violence), people named in a written police request, and staff or contractors who enrol for access by explicit consent. No one is listed on suspicion alone.
- **Who decides**: entries are added by the Chief Security Officer or a named deputy, with a written reason and a reference to the supporting document.
- **Expiry**: every entry has an end date, at most 12 months away; the CSO reviews the list every 3 months and removes entries that are no longer justified.
- **No sensitive grounds**: no entry may be based on ethnicity, religion, political opinion, union membership, health or any similar characteristic.
- **Images**: enrolment photos come from the documented source, are stored encrypted, and are deleted when the entry is removed.
- **Plates**: the same rules apply to plate watchlist entries.

## 10. Accuracy, bias and human review

Face recognition makes mistakes, and accuracy can differ between groups of people and lighting conditions. The site will:

- Measure accuracy in trial stages 2 and 3 on its own cameras, including the false match rate at the chosen threshold, before go-live, and keep the results with the DPIA.
- Use a threshold that favours missing a match over wrongly matching someone.
- Treat every match as a lead, not a fact. A trained person compares the live image with the watchlist image before anyone stops, questions or refuses entry to a person.
- Never take an adverse decision about a person based solely on an automated match.
- Record the outcome of each reviewed match (confirmed, wrong person, unclear), so accuracy can be checked over time.

## 11. Retention

| Data | Kept for |
|---|---|
| Face templates of people not on the watchlist | Not kept: discarded immediately |
| Plate reads with no watchlist match | 30 days, then deleted |
| Match alerts, images and review outcome | 90 days, or until any incident or legal claim they belong to is closed |
| Watchlist entries and enrolment images | Until the entry's end date or removal, whichever is first |
| Evidence exported for police or legal proceedings | As long as the proceedings require, recorded in the incident |
| Audit log of who did what | At least 2 years |

## 12. Security and access

- The system runs on the site's own server; video and templates do not leave the site. A hosted option needs a separate review of transfers outside Nigeria if servers are abroad.
- Only named users with the administrator or CSO role can manage watchlists or see match images; operators see alerts for review.
- All users sign in with their own account; administrators and the CSO use two-factor sign-in.
- Every view, change, export and acceptance is written to the audit log.
- Templates, enrolment images and device passwords are stored encrypted; backups are protected the same way.
- A personal data breach is reported to the NDPC within 72 hours of becoming aware of it, and to affected people where the risk to them is high.

## 13. People's rights and requests

People can ask to see the data held about them, to correct it, to have it erased, to object to the processing, and not to be subject to solely automated decisions. The site will:

- Name a person (the Data Protection Officer or a delegate) to receive and answer requests within the time limits of the NDPA.
- Be able to find a person's watchlist entry and match records, and export or delete them.
- Protect other people in the same images (blur or crop) when giving copies.
- Share data with the police only on a written request, recorded in the incident, and only what is needed.

## 14. Conditions for unlocking

The features are unlocked only when the site owner commits to each of these conditions:

1. A qualified legal practitioner has reviewed this document and given a written opinion that the chosen features may lawfully be used at this site, naming the lawful basis and, for face recognition, the section 30 condition.
2. A data protection impact assessment has been completed, signed and filed, and NDPC prior consultation has been carried out if the DPIA found high remaining risk.
3. A Data Protection Officer (or responsible person) is appointed, and the site's registration and compliance filing duties with the NDPC have been checked and met.
4. Signs are in place at every entrance and vehicle gate covered by recognition, and the privacy notice and staff notice have been published.
5. The watchlist rules in section 9 are adopted, and only the named CSO or deputy will add entries.
6. Every match is reviewed by a trained person before action is taken, and no adverse decision is taken solely on an automated match.
7. The retention periods in section 11 are accepted.
8. Recognition is enabled only on cameras qualified for it, never in private or sensitive areas.
9. Data will be used only for site security, as described in section 5.
10. This review and the DPIA will be reviewed at least every 12 months and whenever purposes, cameras or the law change.

## 15. Sign-off

The acceptance in the console records: the person accepting (their account, name and position), the legal practitioner and firm who gave the opinion, the opinion's reference and date, the DPIA reference, which features are unlocked (face, plate or both), and the exact version of this document. A paper copy signed by the legal practitioner and the site owner's representative should be kept with the DPIA.
