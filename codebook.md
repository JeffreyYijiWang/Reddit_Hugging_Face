# Re-identification research codebook

Version 1.0. This is an operational research rubric, not a validated taxonomy copied from a paper. The user's latest instruction makes comment reconstruction optional and prioritizes scanning the whole available dataset. Post-only classification must report that coverage.

## Source crosswalk

[Kang, Brown and Kiesler (CHI 2013)](https://www.cs.cmu.edu/~kiesler/publications/2013/2013_why-people-seek-anonymity.pdf), pp. 2657-2666, reports interviews with 44 people who sought online anonymity. Table 1, p. 2659 (PDF p. 3), groups anonymous activities. We adapt those activity labels to post intent; the paper gives examples rather than a complete post-coding manual. The definitions below are this project's choices.

The personal-threat discussion on p. 2661 (PDF p. 5) distinguishes malicious actors, institutions/businesses, familiar people, community participants and unspecified others. Workbook categories are discovery provenance, not automatically the event's actual threat. Institutional/organizational queries divide some concerns differently. Reporter/finder party labels and relationship degrees are project extensions, not verbatim paper categories. Discussion of boundaries and identity strategies on pp. 2662-2663 motivates recording stated protection beliefs separately from observed behavior. Neither an anonymous account nor a post establishes private browsing or the user's unspoken beliefs.

## Intent options and operational rules

Code from the original post when established; otherwise leave Unclear or mark original resolution provisional. Multiple purposes are permitted, with one primary and secondary labels. Do not classify a missing original from an update's purpose.

| Requested option | This project's operational definition |
|---|---|
| Browsing and searching for information | Explicitly described information-seeking behavior; a Reddit post alone does not establish browsing. |
| Filesharing and downloading | Sharing or obtaining downloadable files is the post's principal purpose. |
| Participating in special interest groups | Participation organized around a hobby or shared topic; distinguish specific support requests. |
| Social networking | Building or maintaining interpersonal contact is the principal purpose. |
| Sharing art and/or work | Presenting authored creative/professional output, including requests for feedback. |
| Exchanging help or support | Requesting/providing advice, practical help, emotional or peer support. |
| Buying and/or selling | A transaction or solicitation to transact. |
| Discussing politics or news | Political discussion, with **news added by this project**. |
| Reviewing and/or recommending | Evaluating or recommending a product, service or experience. |
| Unclear | Insufficient evidence or conflicting purposes that cannot be resolved. |

## Reported-event decision

- Yes: clear report that a post/account was connected to an author, a subject recognized themselves/someone known, or accounts were explicitly linked. This confirms a *report*, not the story's independent truth.
- No: sufficient reviewed material establishes a nonqualifying event, fear/prevention only, failed attempts, or ordinary content discovery without a person/account connection.
- Unsure: missing, ambiguous, contradictory or unreviewed evidence. Unreviewed rows always carry a pending status.

Examples below are synthetic, never corpus findings:

- “My colleague found my anonymous post and recognized me from the situation” is potentially qualifying with context.
- “If my colleague found my post, I would be in trouble” is hypothetical.
- “My colleague found my post useful” may describe usefulness, not identity recognition.
- “Throwaway because my partner knows my main” is precautionary, not a report that the throwaway was found.
- A comment quoting another author's disclosure must retain quoted attribution. A narrator's unrelated anecdote must not become the containing post's OP incident.
- Voluntary showing can connect identity but is separately flagged; do not silently count it as involuntary discovery.

Lexical triage flags only help review sampling. They never assign final Yes/No labels.

## Actors, evidence, series and preservation

Reporter: OP/author; Subject of post; Mutual connection; Stranger; Other; Unclear. Finder: Subject of post; Second party connected to both OP and subject; Third party connected to subject but not OP; Complete stranger; Other; Unclear. These party names are not graph distances.

Relationship requested category: First-degree connection; Second-degree connection; **Third-degree connection or greater / Stranger (other reddit users)**; Other; Unclear. Separately record observed graph distance, unknown for strangers unless explicitly evidenced. Preserve spouse, sibling, parent, extended family, friend, customer, employee, coworker, boss/supervisor, friend of friend, documented intermediary, partner/ex-partner, stranger, other, unclear subtypes.

Evidence types: Comment from Redditor on OG thread; Comment from OP on thread; Separate post from involved party; Update in OG post from OP; Update in separate post from OP; Other; Unclear. Each item needs exact quote/raw offsets, field, record/thread ID, URL, author/role, creation timestamp, edit time when available, event-time expression and attribution. Creation/reporting time is not necessarily event time.

Discovery chains permit Browsing Reddit; Reposted/shared on external social media (platform); Shared by mutual connection; OP voluntarily showed post; Other; Unclear. Preserve ordering when supported. Identifying clues may be situation, timing, location, relationship details, writing, screenshot/image, reused username, accumulated history, other/unclear. Label reported explanation versus researcher inference.

Series status: One-off; One in a series; Unclear. No observed update is not evidence of one-off. Count observed members, supported total, pre-discovery members and later updates separately. Explicit links plus contextual series evidence support provisional edges; bare links, same author or similar titles remain candidates. Do not merge deleted authors. A thread can contain multiple incidents; multiple posts can describe one incident. Final consolidation requires evidence review.

Preservation categories: subreddit automod in comments; another Redditor in comments; another subreddit; external platform; none observed; unknown. Detect for every collected post, including accessible originals. Automated exact-text/cue detection is a review aid; cue-only copies require attribution checks. External preservation sources are not fetched automatically and remain unsearched. Preserve source and completeness. Preservation location is not discovery location.

## Accounts, outcomes, metrics and missingness

Current account status: Deleted; Banned or suspended; Exists (activity unverified); Still active with supporting observation; Unknown. Archived authorship is not current activity, and inaccessible profiles do not establish a deletion reason. Requested type: Burner/one-time use; Not burner; Unclear. Record declared throwaway, declared intended one-time use and observed reuse separately. A username or one observation is insufficient.

Outcomes: Break-up; Abuse—verbal harassment; Abuse—physical altercation; Abuse—cyberharassment; Unwanted contact; Blackmail/coercion (including coerced updates); Legal action; Reconciliation; Family friction; New truths/added clarity; Public shaming; Other; Unclear. Multiple outcomes are allowed. Each needs evidence, affected person, timing and causal attribution. Preexisting abuse is not automatically caused by discovery. No outcome reported differs from explicit no repercussions.

Unknown factual values remain null with reasons: not_in_source, not_reported, outside_archive_coverage, ambiguous, not_applicable, not_reviewed or not_collected. Account age needs account creation time. Observed pre-post activity is a separately named lower bound using strict time inequality, not lifetime history. Include target subreddit in that proxy only under an explicit convention. Contemporary visitors/contributors/traffic cannot be replaced by current metrics or archive counts. Score is net score. Preserve num_comments and retrieved comments as separate measures. Do not infer is_self solely from empty text.

## Qualification and evaluation

Store all candidates, including eventual No and Unsure. Code exact spans against raw full source text. Model inputs contain full original text and all collected material through traceable batches. Post-only coverage is explicit; no snippet-only result claims all-thread review. Models must return schema-valid JSON; invalid quotes/errors remain pending review. Full archive text is never sent to the model.

Review sampling stratifies query family, record kind and available classification/triage labels; negative convenience records are separately labeled. Precision and agreement require adjudicated labels. Known-case retrieval coverage is not population recall. With no supplied adjudication set, these estimates remain unavailable.

Canonical schema: `reddit_reid/schema.py` and generated `data/inputs/annotation.schema.json`. The review export's 42 requested columns retain order. Additional structured fields are appended and full JSON retained. “Confirmed URL” means evidence record URL; seed metadata and provisional original metadata remain distinct. Long cells have complete Text parts and canonical-file references. Formula-like source strings are escaped only in spreadsheets/CSV.
