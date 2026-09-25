"""Complete project codebook schema; unknown is distinct from No/zero."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

INTENTS = ["Browsing and searching for information", "Filesharing and downloading", "Participating in special interest groups", "Social networking", "Sharing art and/or work", "Exchanging help or support", "Buying and/or selling", "Discussing politics or news", "Reviewing and/or recommending", "Unclear"]
EVIDENCE_TYPES = ["Comment from Redditor on OG thread", "Comment from OP on thread", "Separate post from involved party", "Update in OG post from OP", "Update in separate post from OP", "Other", "Unclear"]
OUTCOMES = ["Break-up", "Abuse—verbal harassment", "Abuse—physical altercation", "Abuse—cyberharassment", "Unwanted contact", "Blackmail/coercion", "Legal action", "Reconciliation", "Family friction", "New truths/added clarity", "Public shaming", "Other", "Unclear"]
RELATIONSHIPS = ["First-degree connection", "Second-degree connection", "Third-degree connection or greater / Stranger (other reddit users)", "Other", "Unclear"]
SUBTYPES = ["spouse", "sibling", "parent", "extended family", "friend", "customer", "employee", "coworker", "boss/supervisor", "friend of friend", "other documented intermediary", "partner/ex-partner", "stranger", "other", "unclear"]
PRESERVATION_TYPES = ["subreddit automod in comments", "another Redditor in comments", "another subreddit", "external platform", "none observed", "unknown"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Strict):
    evidence_id: str
    quote: str
    raw_start: int
    raw_end: int
    source_record_id: str
    thread_id: str | None = None
    permalink: str | None = None
    source_field: Literal["title", "selftext", "body"]
    reporting_username: str | None = None
    role_relative_to_original_op: str = "Unclear"
    record_created_utc: int | None = None
    edit_timestamp: int | None = None
    event_time_expression: str | None = None
    content_type: Literal[tuple(EVIDENCE_TYPES)] = "Unclear"
    attribution: Literal["author's own statement", "quoted or preserved text", "unclear"] = "unclear"


class PostProperties(Strict):
    post_id: str | None = None
    subreddit: str | None = None
    permalink: str | None = None
    title: str | None = None
    full_text: str | None = None
    created_utc: int | None = None
    source_repository: str | None = None
    source_revision: str | None = None
    source_shard: str | None = None
    retrieved_at: str | None = None
    archive_observed_at: str | None = None
    status: Literal["Still accessible", "Deleted by OP", "Deleted by subreddit moderators", "Unknown", "Other removal"] = "Unknown"
    status_observed_at: str | None = None
    deletion_responsible_actor: str | None = None
    status_basis: str = "Current accessibility not checked; archive availability is separate"
    archive_text_availability: Literal["text", "empty", "deleted placeholder", "removed placeholder", "missing"] = "missing"
    primary_intent: Literal[tuple(INTENTS)] = "Unclear"
    secondary_intents: list[Literal[tuple(INTENTS)]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class Series(Strict):
    status: Literal["One-off", "One in a series", "Unclear"] = "Unclear"
    observed_post_ids: list[str] = Field(default_factory=list)
    observed_count: int = 0
    supported_total_count: int | None = None
    total_estimate_basis: str | None = None
    count_prior_to_reidentification: int | None = None
    later_update_ids: list[str] = Field(default_factory=list)
    missing_link_ids: list[str] = Field(default_factory=list)
    complete: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class Actors(Strict):
    reporters: list[Literal["OP/author", "Subject of post", "Mutual connection", "Stranger", "Other", "Unclear"]] = Field(default_factory=lambda: ["Unclear"])
    finders: list[Literal["Subject of post", "Second party connected to both OP and subject", "Third party connected to subject but not OP", "Complete stranger", "Other", "Unclear"]] = Field(default_factory=lambda: ["Unclear"])
    finder_relationship_requested_category: Literal[tuple(RELATIONSHIPS)] = "Unclear"
    finder_relationship_subtypes: list[Literal[tuple(SUBTYPES)]] = Field(default_factory=lambda: ["unclear"])
    finder_graph_distance_observed: int | None = None
    finder_graph_distance_basis: str | None = None
    reporter_finder_distinction: str | None = None
    subject_referred_to: str | None = None
    target_is_containing_thread_op: bool | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class DiscoveryStep(Strict):
    path: Literal["Browsing Reddit", "Reposted/shared on external social media", "Shared by mutual connection", "OP voluntarily showed post", "Other", "Unclear"]
    platform: str | None = None
    order: int | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class Discovery(Strict):
    chain: list[DiscoveryStep] = Field(default_factory=list)
    found_time_start: str | None = None
    found_time_end: str | None = None
    original_time_expression: str | None = None
    time_precision: str | None = None
    time_derivation: str | None = None
    notes: str | None = None
    claimed_identifying_clues: list[Literal["situation", "timing", "location", "relationship details", "writing", "image/screenshot", "username reuse", "history accumulation", "other", "unclear"]] = Field(default_factory=list)
    mechanism_basis: Literal["reported explanation", "researcher inference", "unclear"] = "unclear"
    evidence_refs: list[str] = Field(default_factory=list)


class Preservation(Strict):
    post_id: str
    type: Literal[tuple(PRESERVATION_TYPES)] = "unknown"
    source_record_id: str | None = None
    source_url: str | None = None
    attribution: str | None = None
    timestamp: int | None = None
    completeness: Literal["full", "partial", "unknown"] = "unknown"
    copied_original_metadata: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    detection_status: str = "pending review"


class Account(Strict):
    status: Literal["Deleted", "Banned or suspended", "Exists (activity unverified)", "Still active with supporting observation", "Unknown"] = "Unknown"
    status_observation_date: str | None = None
    requested_type: Literal["Burner/one-time use", "Not burner", "Unclear"] = "Unclear"
    declared_throwaway: bool | None = None
    declared_intended_one_time_use: bool | None = None
    observed_reuse: bool | None = None
    observed_activity_counts: dict = Field(default_factory=dict)
    observation_window: dict = Field(default_factory=dict)
    perceived_protection_statement: str | None = None
    perceived_protection_change: str | None = None
    author_discovery_explanation: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class Outcome(Strict):
    label: Literal[tuple(OUTCOMES)]
    affected_person: str | None = None
    timing: str | None = None
    attributed_to_reidentification: bool | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class Annotation(Strict):
    schema_version: str = "1.0"
    incident_id: str
    seed_record_ids: list[str] = Field(default_factory=list)
    original: PostProperties = Field(default_factory=PostProperties)
    post_properties: list[PostProperties] = Field(default_factory=list)
    original_resolution_status: Literal["established", "provisional seed thread", "unresolved"] = "unresolved"
    confirmed_reidentification: Literal["Yes", "No", "Unsure"] = "Unsure"
    evidence_basis: list[Literal["OP self-report", "involved-party claim", "corroborated within thread", "third-party report", "unclear"]] = Field(default_factory=lambda: ["unclear"])
    identity_connection_type: list[Literal["author recognized", "subject recognized", "accounts linked", "other", "unclear"]] = Field(default_factory=lambda: ["unclear"])
    voluntary_disclosure: bool | None = None
    rationale: str = "Awaiting full-bundle review"
    review_status: str = "pending_model_and_human_review"
    review_coverage: dict = Field(default_factory=dict)
    series: Series = Field(default_factory=Series)
    evidence: list[Evidence] = Field(default_factory=list)
    actors: Actors = Field(default_factory=Actors)
    discovery: Discovery = Field(default_factory=Discovery)
    preservation: list[Preservation] = Field(default_factory=list)
    account: Account = Field(default_factory=Account)
    outcomes: list[Outcome] = Field(default_factory=list)
    no_outcome_reported: bool | None = None
    explicitly_no_repercussions: bool | None = None
    metrics: dict = Field(default_factory=dict)
    missingness: dict = Field(default_factory=dict)
    claim_evidence: dict[str, list[str]] = Field(default_factory=dict)
    collection_coverage: dict = Field(default_factory=dict)
    additional_incidents: list[dict] = Field(default_factory=list)
    annotation_provenance: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def labels_need_evidence(self):
        if self.confirmed_reidentification == "Yes" and not self.evidence:
            raise ValueError("Yes requires an exact evidence span")
        if self.confirmed_reidentification != "Unsure" and self.review_status.startswith("pending"):
            raise ValueError("Unreviewed is not Yes or No")
        if "stranger" in self.actors.finder_relationship_subtypes and self.actors.finder_graph_distance_observed is not None and not self.actors.finder_graph_distance_basis:
            raise ValueError("Stranger does not imply a social-graph distance")
        refs = {e.evidence_id for e in self.evidence}
        def walk(v, key=""):
            if isinstance(v, dict):
                for k, x in v.items():
                    walk(x, k)
            elif isinstance(v, list):
                if key == "evidence_refs" and not set(v) <= refs:
                    raise ValueError("Unknown evidence reference")
                for x in v:
                    walk(x)
        walk(self.model_dump())
        for key, values in self.claim_evidence.items():
            if not values or not set(values) <= refs:
                raise ValueError(f"Invalid claim evidence: {key}")
        return self


def validate_spans(annotation, records):
    by_id = {r["typed_id"]: r for r in records}
    for ev in annotation.evidence:
        if ev.source_record_id not in by_id:
            raise ValueError("Evidence source outside retrieved bundle")
        row = by_id[ev.source_record_id]
        text = row.get(ev.source_field) or ""
        if not (0 <= ev.raw_start < ev.raw_end <= len(text)) or text[ev.raw_start:ev.raw_end] != ev.quote:
            raise ValueError("Evidence quote/offset mismatch")
        if ev.thread_id != row["thread_id"]:
            raise ValueError("Evidence thread mismatch")
        if ev.record_created_utc != row.get("created_utc") or ev.reporting_username != row.get("author"):
            raise ValueError("Evidence metadata must come from source")
    return annotation
