from __future__ import annotations

import json
import re
from typing import Any

import requests

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
REQUEST_TIMEOUT_SECONDS = 30


def _get_json(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(
        f"{EUTILS_BASE_URL}{endpoint}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _extract_year(pubdate: str | None) -> str | None:
    if not pubdate:
        return None
    match = re.search(r"(19|20)\d{2}", pubdate)
    return match.group(0) if match else None


def _extract_doi(summary: dict[str, Any]) -> str | None:
    article_ids = summary.get("articleids", []) or []
    for article_id in article_ids:
        id_type = str(article_id.get("idtype", "")).lower()
        if id_type == "doi":
            value = article_id.get("value")
            if value:
                return str(value)

    elocation_id = summary.get("elocationid")
    if isinstance(elocation_id, str):
        match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", elocation_id, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def search_pubmed(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    max_results = max(1, min(max_results, 100))
    esearch_data = _get_json(
        "esearch.fcgi",
        {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": max_results,
        },
    )
    id_list = esearch_data.get("esearchresult", {}).get("idlist", []) or []
    if not id_list:
        return []

    esummary_data = _get_json(
        "esummary.fcgi",
        {
            "db": "pubmed",
            "id": ",".join(id_list),
            "retmode": "json",
        },
    )
    result = esummary_data.get("result", {})
    ordered_uids = result.get("uids", []) or id_list

    papers: list[dict[str, Any]] = []
    for uid in ordered_uids:
        summary = result.get(str(uid), {})
        authors = [
            author.get("name", "")
            for author in summary.get("authors", [])
            if isinstance(author, dict) and author.get("name")
        ]
        papers.append(
            {
                "pmid": str(uid),
                "title": summary.get("title") or "",
                "authors": authors,
                "journal": summary.get("fulljournalname") or summary.get("source") or "",
                "year": _extract_year(summary.get("pubdate")),
                "doi": _extract_doi(summary),
            }
        )
    return papers


def fetch_abstract(pmid: str) -> str:
    response = requests.get(
        f"{EUTILS_BASE_URL}efetch.fcgi",
        params={
            "db": "pubmed",
            "id": pmid,
            "rettype": "abstract",
            "retmode": "text",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.text.strip()


def _extract_n50_fields(summary: dict[str, Any]) -> tuple[str | None, str | None]:
    def _from_stats(stats: Any) -> tuple[str | None, str | None]:
        scaffold_n50: str | None = None
        contig_n50: str | None = None
        if isinstance(stats, list):
            for item in stats:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("stat_name", "")).lower()
                value = item.get("stat_val")
                if value is None:
                    continue
                if "scaffold n50" in name:
                    scaffold_n50 = str(value)
                if "contig n50" in name:
                    contig_n50 = str(value)
        return scaffold_n50, contig_n50

    scaffold_n50 = summary.get("scaffoldn50")
    contig_n50 = summary.get("contign50")

    meta_raw = summary.get("meta")
    if isinstance(meta_raw, str) and meta_raw:
        try:
            meta = json.loads(meta_raw)
            stats = meta.get("assembly_stats") or meta.get("stats")
            stats_scaffold, stats_contig = _from_stats(stats)
            scaffold_n50 = scaffold_n50 or stats_scaffold
            contig_n50 = contig_n50 or stats_contig
        except json.JSONDecodeError:
            pass

    return (
        str(scaffold_n50) if scaffold_n50 is not None else None,
        str(contig_n50) if contig_n50 is not None else None,
    )


def check_reference_genome(organism: str) -> dict[str, Any]:
    term = (
        f"{organism}[Organism] AND "
        "(latest[filter] AND (reference genome[filter] OR representative genome[filter]))"
    )
    esearch_data = _get_json(
        "esearch.fcgi",
        {
            "db": "assembly",
            "term": term,
            "retmode": "json",
            "retmax": 1,
        },
    )
    id_list = esearch_data.get("esearchresult", {}).get("idlist", []) or []
    if not id_list:
        return {
            "organism": organism,
            "has_reference": False,
            "assembly_name": None,
            "scaffold_n50": None,
            "contig_n50": None,
        }

    esummary_data = _get_json(
        "esummary.fcgi",
        {
            "db": "assembly",
            "id": id_list[0],
            "retmode": "json",
            "report": "full",
        },
    )
    result = esummary_data.get("result", {})
    uids = result.get("uids", [])
    uid = str(uids[0]) if uids else str(id_list[0])
    summary = result.get(uid, {}) if isinstance(result, dict) else {}

    scaffold_n50, contig_n50 = _extract_n50_fields(summary)

    return {
        "organism": organism,
        "has_reference": True,
        "assembly_name": summary.get("assemblyname") or summary.get("assembly_name"),
        "scaffold_n50": scaffold_n50,
        "contig_n50": contig_n50,
    }
