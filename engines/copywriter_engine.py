"""
engines/copywriter_engine.py

Generates marketing copy for landing pages.
Converted from V1 paginas/copywriter.py.
Integrates with existing LLM orchestration in V2.
"""
import json
from infrastructure.logger import get_logger
from infra.llm.llm_client import generate

logger = get_logger("CopywriterEngine")

class CopywriterEngine:
    def generate_sales_copy(self, product_context: dict) -> dict:
        """
        Generates structured sales copy based on product context.
        Uses V2's robust LLM client which natively handles retries/fallbacks.
        """
        logger.info(f"[CopywriterEngine] Generating copy for: {product_context.get('title', 'Unknown Product')}")
        
        prompt = f"""
        Write high-converting sales copy for a landing page.
        
        Product: {product_context.get('title')}
        Description: {product_context.get('description')}
        Target Pain: {product_context.get('cluster_name', 'General Pain')}
        Pain Score: {product_context.get('aggregate_pain_score', 'N/A')}
        
        Structure your response as a valid JSON object with EXACTLY these keys:
        - "headline": (Punchy, outcome-focused string)
        - "subheadline": (Clarifies the offer string)
        - "pain_agitation": (Empathize with the problem string)
        - "solution_promise": (How we fix it string)
        - "benefits": (List of 3-5 key benefits as array of strings)
        - "features": (List of 3-5 key features as array of strings)
        - "cta_text": (Action verb string)
        - "pricing_text": (Pricing text string)
        - "faq": (List of 3 Q&A pairs as array of objects with 'q' and 'a')

        Tone: Professional, urgent, persuasive.
        You must output ONLY valid JSON, no markdown blocks.
        """
        
        # Call the existing V2 LLM Client
        response = generate(
            prompt=prompt,
            model="gpt-4o",
            temperature=0.7,
            system_prompt="You are a world-class direct response copywriter. Output only valid JSON."
        )
        
        if response.get("status") == "ok":
            content = response.get("content", "{}").strip()
            
            try:
                # Clean up if the model wrapped output in markdown
                if content.startswith("```json"):
                    content = content[7:-3].strip()
                elif content.startswith("```"):
                    content = content[3:-3].strip()
                    
                parsed_data = json.loads(content)
                logger.info("[CopywriterEngine] Copy generated successfully.")
                return parsed_data
                
            except json.JSONDecodeError as e:
                logger.error(f"[CopywriterEngine] JSON parsing failed: {e}\nRaw Content:\n{content}")
        else:
            logger.error(f"[CopywriterEngine] Generation error: {response.get('error_type')}")
                
        logger.warning("[CopywriterEngine] Returning safe fallback copy structure.")
        
        return {
            "headline": "Stop Wasting Time on Inefficient Workflows",
            "subheadline": "Automate your daily tasks with our proven system.",
            "pain_agitation": "Are you tired of manually doing repetitive work?",
            "solution_promise": "Our solution fixes it instantly.",
            "benefits": ["Save 10+ hours per month", "Eliminate errors", "No coding skills required"],
            "features": ["Easy setup", "Lifetime updates", "Premium support"],
            "cta_text": "Get Instant Access",
            "pricing_text": "Special Offer",
            "faq": []
        }

# Singleton export
copywriter_engine = CopywriterEngine()

def generate_sales_copy(product_context: dict) -> dict:
    """Wrapper for external calls."""
    return copywriter_engine.generate_sales_copy(product_context)
