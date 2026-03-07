"""
core/landing_generation_engine.py — Landing Generation Engine (C3_MARKET_01)
Generates an LLM-powered landing page with automatic fallback.
"""
import os
from pathlib import Path
from infrastructure.logger import get_logger

logger = get_logger("LandingGenerationEngine")

class _OpenAIAdapter:
    def generate(self, prompt: str) -> str:
        import openai
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY missing")
        
        client = openai.OpenAI(api_key=api_key)
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                timeout=20
            )
            return response.choices[0].message.content
        except openai.APITimeoutError:
            logger.error("OpenAI request timed out")
            raise
        except openai.RateLimitError:
            logger.error("OpenAI rate limit reached")
            raise
        except Exception as e:
            logger.error(f"OpenAI error: {e}")
            raise

class _GeminiAdapter:
    def generate(self, prompt: str) -> str:
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai library not installed")
            
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY missing")
            
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        
        # Timeout handling for Gemini Pro (20s)
        response = model.generate_content(prompt, request_options={"timeout": 20})
        return response.text

class _StaticFallbackAdapter:
    def __init__(self, engine):
        self.engine = engine
        
    def generate(self, product_id: str, headline: str, price: float) -> str:
        subheadline = "The fastest way to achieve your outcome."
        bullets = [
            "Immediate results with minimal setup.",
            "Designed for high-impact decision making.",
            "Scalable micro-product architecture."
        ]
        return self.engine._build_html(product_id, headline, subheadline, bullets, price)

class LandingGenerationEngine:
    def __init__(self, output_dir: str = "generated_landings"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._static = _StaticFallbackAdapter(self)

    def generate_landing(self, product_id: str, transformation_statement: str, price: float, orchestrator) -> str:
        """
        Generates an LLM-powered HTML landing page based on the product statement.
        """
        provider_env = os.getenv("LANDING_LLM_PROVIDER", "openai").lower()
        
        # Fallback chain configuration
        if provider_env == "gemini":
            chain = ["gemini", "openai", "static"]
        else:
            chain = ["openai", "gemini", "static"]
            
        prompt = (
            f"Generate a professional, high-converting HTML landing page for '{transformation_statement}'. "
            f"The price is ${price:.2f}. Must include <html> tag, <body>, a headline, subheadline, and a button "
            f"with id='checkout-btn'. Return ONLY the HTML code."
        )
        
        html_content = None
        final_provider = "static"
        
        for p_name in chain:
            try:
                if p_name == "openai":
                    html_content = _OpenAIAdapter().generate(prompt)
                elif p_name == "gemini":
                    html_content = _GeminiAdapter().generate(prompt)
                elif p_name == "static":
                    html_content = self._static.generate(product_id, transformation_statement, price)
                
                # Validation: length > 400 and contains <html
                if html_content and len(html_content) > 400 and "<html" in html_content.lower():
                    final_provider = p_name
                    logger.info(f"Successfully generated landing using {p_name}")
                    break
                else:
                    if p_name != "static":
                        logger.warning(f"Provider {p_name} output failed validation. Falling back.")
            except Exception as e:
                if p_name != "static":
                    logger.error(f"Provider {p_name} failed: {type(e).__name__}. Falling back.")
                continue

        # Resilience: ensure we have content
        if not html_content:
            html_content = self._static.generate(product_id, transformation_statement, price)
            final_provider = "static"

        file_path = self.output_dir / f"{product_id}.html"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Emit formal event via Orchestrator
        orchestrator.emit_event(
            event_type="landing_created",
            product_id=product_id,
            payload={
                "product_id": product_id,
                "file_path": str(file_path),
                "price": price,
                "provider": final_provider
            }
        )

        return str(file_path)

    def _build_html(self, product_id: str, headline: str, subheadline: str, bullets: list, price: float) -> str:
        bullets_html = "".join([f"<li>{b}</li>" for b in bullets])
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{headline}</title>
    <style>
        body {{ font-family: sans-serif; text-align: center; padding: 50px; background: #f4f7f6; }}
        .container {{ max-width: 600px; margin: auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; margin-bottom: 10px; }}
        h2 {{ color: #7f8c8d; font-weight: normal; margin-top: 0; }}
        ul {{ text-align: left; margin-top: 20px; }}
        .price {{ font-size: 24px; font-weight: bold; color: #27ae60; margin: 20px 0; }}
        .cta {{ display: inline-block; background: #e67e22; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; cursor: pointer; }}
        .cta.loading {{ opacity: 0.7; pointer-events: none; }}
    </style>
</head>
<body data-product-id="{product_id}">
    <div class="container">
        <h1>{headline}</h1>
        <h2>{subheadline}</h2>
        <ul>
            {bullets_html}
        </ul>
        <div class="price">${price:.2f}</div>
        <button id="checkout-btn" class="cta">Get Started Now</button>
    </div>

    <script>
        document.getElementById('checkout-btn').addEventListener('click', async function() {{
            const btn = this;
            const productId = document.body.getAttribute('data-product-id');
            
            btn.classList.add('loading');
            btn.innerText = 'Redirecting...';

            try {{
                const response = await fetch('/create-checkout-session', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ product_id: productId }})
                }});

                const data = await response.json();
                if (data.checkout_url) {{
                    window.location.href = data.checkout_url;
                }} else {{
                    alert('Error: ' + (data.error || 'Could not create checkout session'));
                    btn.classList.remove('loading');
                    btn.innerText = 'Get Started Now';
                }}
            }} catch (err) {{
                console.error(err);
                alert('Connection error. Please try again.');
                btn.classList.remove('loading');
                btn.innerText = 'Get Started Now';
            }}
        }});
    </script>
</body>
</html>
"""
