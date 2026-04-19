Overview: What our Project is About
Agnes is an AI-powered decision-support system designed to tackle supply chain fragmentation in the Consumer Packaged Goods (CPG) industry. Large companies often overpay because identical ingredients or packaging materials are purchased independently across different plants or product lines. Agnes acts as an intelligent supply chain assistant that connects this fragmented data to uncover true buying volumes and help buyers regain leverage on price, lead times, and service levels.

The Main Task
The primary goal of the project is to analyze normalized Bill of Materials (BOMs) and supplier data to identify components that are functionally interchangeable. However, the system goes far beyond simple cost optimization: it must evaluate whether a cheaper or consolidated substitute still strictly satisfies the quality and compliance requirements of the finished product. To build trust, every recommended sourcing decision is accompanied by a transparent "evidence trail" that explains the tradeoffs between supplier consolidation, cost, and compliance.

External Enrichment & Web Scraping
Because internal procurement data is often messy and incomplete, external data enrichment is a critical pillar of this solution. The system utilizes web scraping and data sourcing to fetch missing evidence from the outside world. By pulling in external information—such as supplier websites, product listings, certification databases, and regulatory references—the AI reasoning layer can confidently infer if a proposed substitute meets all necessary compliance constraints.

API Management & Architecture
The backend is built with FastAPI and is fully equipped to serve client interfaces, such as a mobile app, via RESTful endpoints.

AI Integration (Gemini): The core intelligence of Agnes is driven by the Gemini API, powered by Google Cloud credits, which handles the complex LLM reasoning and component normalization tasks.

Authentication: API management is strictly enforced, requiring an X-API-Key header for all endpoint access to ensure secure data handling.

Endpoints: The API exposes several endpoints to drive the application:

    - /api/v1/candidates: Fetch top consolidation candidates.

    - /api/v1/substitute: Evaluate substitutions with full evidence trails.

    - /api/v1/recommend: Generate consolidated sourcing proposals.

Infrastructure: The system relies on a local SQLite database (db.sqlite) to manage existing company, product, and BOM relationships, which is seamlessly integrated with the LLM reasoning (RAG) and caching layers.