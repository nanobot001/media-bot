import logging
import time
from typing import Optional, Any, Dict, List, Tuple
import httpx

logger = logging.getLogger(__name__)

class WikidataFactProvider:
    """
    Retrieves authority-backed facts for movies from Wikidata.
    Bypasses WDQS SPARQL endpoint to avoid active outages and rate limits.
    Uses MediaWiki action API and Entity REST API.
    """

    def __init__(
        self,
        user_agent: str = "MovieBot/1.1 (anthony@example.com)",
        request_interval_seconds: float = 1.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 30.0,
    ):
        self.headers = {"User-Agent": user_agent}
        self.client = httpx.Client(headers=self.headers, timeout=15.0)
        self.request_interval_seconds = request_interval_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._last_request_at = 0.0
        self._rate_limited = False

    def _sleep_for_pacing(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        for attempt in range(self.max_retries + 1):
            self._sleep_for_pacing()
            self._last_request_at = time.monotonic()
            try:
                res = self.client.get(url, params=params)
                if res.status_code == 429:
                    self._rate_limited = True
                    retry_after = res.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else self.retry_backoff_seconds * (attempt + 1)
                    except ValueError:
                        delay = self.retry_backoff_seconds * (attempt + 1)
                    logger.warning("Wikidata rate limited request; sleeping %.1fs before retry", delay)
                    if attempt >= self.max_retries:
                        return None
                    time.sleep(delay)
                    continue
                res.raise_for_status()
                return res.json()
            except Exception as e:
                if attempt >= self.max_retries:
                    logger.warning(f"Error requesting Wikidata API: {e}")
                    return None
                time.sleep(self.retry_backoff_seconds * (attempt + 1))
        return None

    def get_qid_by_imdb_id(self, imdb_id: str) -> Optional[str]:
        """Maps IMDb ID to Wikidata QID."""
        if not imdb_id:
            return None
        # Clean ID
        imdb_id = imdb_id.strip()
        url = "https://www.wikidata.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": f"haswbstatement:P345={imdb_id}",
            "format": "json"
        }
        try:
            data = self._get_json(url, params=params)
            search_results = (data or {}).get("query", {}).get("search", [])
            if search_results:
                return search_results[0]["title"]
        except Exception as e:
            logger.warning(f"Error mapping IMDb ID {imdb_id} to QID: {e}")
        return None

    def get_qid_by_title_year(self, title: str, year: Optional[int]) -> Optional[str]:
        """Fall back to searching title and year if IMDb ID is missing or lookup fails."""
        if not title:
            return None
        query = f"{title}"
        if year:
            query += f" {year}"
        query += " film"
        
        url = "https://www.wikidata.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json"
        }
        try:
            data = self._get_json(url, params=params)
            search_results = (data or {}).get("query", {}).get("search", [])
            if search_results:
                # Filter results that look like a QID
                for result in search_results:
                    title_val = result["title"]
                    if title_val.startswith("Q") and title_val[1:].isdigit():
                        return title_val
        except Exception as e:
            logger.warning(f"Error mapping title/year '{title} ({year})' to QID: {e}")
        return None

    def fetch_entity_claims(self, qid: str) -> dict:
        """Retrieves raw entity claims from Wikidata."""
        url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        try:
            data = self._get_json(url)
            return data.get("entities", {}).get(qid, {}).get("claims", {})
        except Exception as e:
            logger.warning(f"Error fetching claims for QID {qid}: {e}")
            return {}

    def extract_facts(self, claims: dict) -> Tuple[Dict[str, List[str]], Optional[float]]:
        """
        Extracts QID references for target properties and gets box office amount.
        Returns:
            - dict mapping target names to lists of referenced QIDs
            - box office amount (float or None)
        """
        target_props = {
            "P2522": "awards_received", # award received
            "P166": "awards_received",   # award received (primary for films)
            "P1411": "nominated_for",    # nominated for
            "P144": "based_on",          # based on
            "P179": "series"             # part of the series
        }
        
        extracted = {
            "awards_received": [],
            "nominated_for": [],
            "based_on": [],
            "series": []
        }
        
        for prop, group_name in target_props.items():
            if prop in claims:
                for claim in claims[prop]:
                    mainsnak = claim.get("mainsnak", {})
                    datavalue = mainsnak.get("datavalue", {})
                    if datavalue.get("type") == "wikibase-entityid":
                        ref_qid = datavalue["value"]["id"]
                        extracted[group_name].append(ref_qid)
        
        # Box Office (P2142)
        box_office = None
        if "P2142" in claims:
            amounts = []
            for claim in claims["P2142"]:
                mainsnak = claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                if datavalue.get("type") == "quantity":
                    amount_str = datavalue["value"]["amount"]
                    if amount_str.startswith("+"):
                        amount_str = amount_str[1:]
                    try:
                        amounts.append(float(amount_str))
                    except ValueError:
                        pass
            if amounts:
                box_office = max(amounts)
                
        return extracted, box_office

    def resolve_labels(self, qids: List[str]) -> Dict[str, str]:
        """Resolves a list of QIDs to their English labels in batches."""
        labels = {}
        if not qids:
            return labels
            
        url = "https://www.wikidata.org/w/api.php"
        qids_list = sorted(list(set(qids)))
        
        for i in range(0, len(qids_list), 50):
            batch = qids_list[i:i+50]
            ids_str = "|".join(batch)
            params = {
                "action": "wbgetentities",
                "ids": ids_str,
                "props": "labels",
                "languages": "en",
                "format": "json"
            }
            try:
                data = self._get_json(url, params=params)
                entities = (data or {}).get("entities", {})
                for q, ent in entities.items():
                    label = ent.get("labels", {}).get("en", {}).get("value")
                    if label:
                        labels[q] = label
            except Exception as e:
                logger.warning(f"Error resolving labels for batch {batch}: {e}")
                
        return labels

    def get_facts(self, title: str, year: Optional[int], imdb_id: Optional[str] = None, qid: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Orchestrates the entire fetching pipeline for a movie.
        Returns:
            dict containing:
                - qid: Wikidata ID
                - box_office: float or None
                - awards_received: list of strings
                - nominated_for: list of strings
                - based_on: list of strings
                - series: list of strings
        """
        if not qid:
            if imdb_id:
                qid = self.get_qid_by_imdb_id(imdb_id)
            if not qid and not self._rate_limited:
                qid = self.get_qid_by_title_year(title, year)
            
        if not qid:
            logger.info(f"Could not find Wikidata QID for movie '{title} ({year})'")
            return None
            
        claims = self.fetch_entity_claims(qid)
        if not claims:
            return None
            
        extracted_qids, box_office = self.extract_facts(claims)
        
        # Gather all QIDs that need label resolution
        all_ref_qids = {qid}
        for qlist in extracted_qids.values():
            all_ref_qids.update(qlist)
            
        labels = self.resolve_labels(list(all_ref_qids))
        
        movie_title = labels.get(qid, title)
        
        return {
            "qid": qid,
            "resolved_title": movie_title,
            "box_office": box_office,
            "awards_received": [labels[q] for q in extracted_qids["awards_received"] if q in labels],
            "nominated_for": [labels[q] for q in extracted_qids["nominated_for"] if q in labels],
            "based_on": [labels[q] for q in extracted_qids["based_on"] if q in labels],
            "series": [labels[q] for q in extracted_qids["series"] if q in labels]
        }
