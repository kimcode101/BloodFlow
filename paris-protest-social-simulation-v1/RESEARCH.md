# Research boundary and Friday–Sunday scenario

Prepared 22 October 2026. Assumed requested weekend: Friday 16 to Sunday 18 October 2026, Europe/Paris (UTC+02:00).

This package contains invented social posts inspired by contemporary reporting. It does not contain scraped posts. Real source documents are research context only. All accounts, post times, local injury claims, hospital appeals, donor interruptions and resolution messages in the dataset are synthetic. A synthetic claim is not a fact about a real person, hospital or protest.

## What the sources establish

- Friday: planned mobilisation across France and unsettled Paris meeting/route information. See SRC-FRI.
- Saturday: transport restrictions appear in the operator's notice. See SRC-RATP. The city's evening statement describes violence and damage alongside peaceful protest. See SRC-CITY-SAT.
- Sunday: a city statement describes cleanup and restoration. See SRC-CITY-SUN. Retrospective journalism adds broad context, but the fetched version also contains a Monday update. See SRC-SUN-REPORT.

These sources do not establish an emergency blood shortage, transfusion requirements, actual hospital inventories, or the synthetic scenario's precise casualties. Metro disruption alone does not establish blocked blood deliveries. Cleanup alone does not establish an all-clear.

## Timing and retrospective leakage

Publication time, update time, event time and collection time differ. Sources were fetched on 22 October. We have no archive proving their earlier versions. The RATP-derived synthetic summary is at 15:20 Saturday, after the observed 15:10 update. The Sunday municipal summary is at 13:40, after the observed 13:30 update. Other posts are invented scenarios; do not treat their times as documented first reports.

A Saturday live-news URL was also inspected but redirected to a 22 October rolling page. It was excluded as an exact Saturday timeline source. Retrospective material can shape the fictional setting, but must not be sent into an earlier simulated decision as evidence available then.

## Source register

### SRC-FRI — Euronews

[Open source](https://fr.euronews.com/2026/10/16/mobilisation-du-17-octobre-qui-manifestera-en-france-et-quelle-ampleur-attendre)

Friday reporting described planned national mobilisation, including Paris, Lyon and Nantes; Paris meeting points and route approval were unsettled.

Limit: Not evidence that each planned action occurred, caused injuries, or affected blood services. Synthetic posts before 13:12 are invented plans, not reconstructions based on an earlier copy of this article.

### SRC-RATP — Bonjour RATP

[Open source](https://www.bonjour-ratp.fr/actualites/articles/manifestation-17-octobre-2026/)

The operator listed Saturday station closures, including Charles-de-Gaulle–Etoile and Concorde from 08:00, and possible bus diversions.

Limit: The fetched version is updated at 15:10. Its earlier contents are not established. Metro closures do not establish blocked blood deliveries.

### SRC-CITY-SAT — Ville de Paris

[Open source](https://pressev2.paris.fr/communiques/la-ville-de-paris-condamne-avec-la-plus-grande-fermete-les-violences-et-les-pillages-commis-dans-la-capitale)

The city reported violence and damage in several districts alongside predominantly peaceful protest, and described its municipal response.

Limit: A municipal account, not a clinical casualty register or a blood-inventory report. No precise synthetic injury or hospital claim is authenticated by it.

### SRC-CITY-SUN — Ville de Paris

[Open source](https://pressev2.paris.fr/communiques/manifestations-du-17-octobre-la-ville-de-paris-mobilise-pres-de-1-000-agents-pour-remettre-en-etat-l-espace-public)

Sunday's municipal update described overnight and morning cleanup and ongoing restoration of public space.

Limit: Recovery work does not prove that every area was calm or that hospital demand had returned to baseline.

### SRC-SUN-REPORT — Le Monde

[Open source](https://www.lemonde.fr/en/france/article/2026/10/18/october-17-french-protests-crowds-marched-through-the-streets-before-violence-looting-and-chaos-broke-out_6758725_7.html)

Retrospective reporting describes Saturday protests across cities and multiple Paris gathering dynamics, including around Opera and Republique.

Limit: Fetched version includes Monday updates. Used only to inspire the broad setting; never injected into Saturday model context. Exact synthetic local injury reports are invented.

## Decision-model documentation

- [TypeSafe: introduction](https://docs.typesafe.ai/introduction) describes typed questions and composing atomic answers in code.
- [OpenAI: Decisions](https://developers.openai.com/api/docs/guides/decisions) describes choice, score, and predicate questions and application-specific threshold validation.

No provider was called in creating this package. The reference decisions are authored expectations, not predictions or measured model accuracy.
