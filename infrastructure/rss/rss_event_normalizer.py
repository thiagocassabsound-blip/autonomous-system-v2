import uuid

class RSSEventNormalizer:
    @staticmethod
    def normalize(parsed_item):
        """
        Takes raw item parsed from RSS, normalizes it.
        Rules:
        - Discard if description < 20 chars
        - Extract potential_problem, context_keywords, intensity_score, recurrence_indicator
        - Generate rss_signal_candidate
        """
        title = parsed_item.get("title", "")
        desc = parsed_item.get("description", "")
        url = parsed_item.get("url", "")
        
        # Noise Filter 1: description < 20 characters
        if len(desc.strip()) < 20:
            return None
            
        text_content = (title + " " + desc).lower()
        
        potential_problem = "Detected issue or topic from source"
        if "fail" in text_content or "bug" in text_content or "pain" in text_content:
            potential_problem = "Failure, bug, or pain point reported"
            
        context_keywords = ["startup"]
        if "ai" in text_content: context_keywords.append("ai")
        if "saas" in text_content: context_keywords.append("saas")
        if "crypto" in text_content: context_keywords.append("crypto")
        
        intensity_score = 1.0
        if "urgent" in text_content or "break" in text_content:
            intensity_score = 3.0
            
        recurrence_indicator = 1
        
        # Signal Generation
        rss_signal = {
            "event_id": str(uuid.uuid4()),
            "timestamp": parsed_item.get("timestamp"),
            "source_name": parsed_item.get("source_name"),
            "source_category": parsed_item.get("category"),
            "title": title,
            "description": desc,
            "url": url,
            "keyword_cluster": context_keywords,
            "signal_strength": intensity_score,
            "origin": "rss_layer"
        }
        return rss_signal
