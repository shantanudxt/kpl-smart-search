# KPL Catalog Search & Query-Relaxation Middleware

A production-grade search proxy and UI wrapper for the Kitchener Public Library (KPL) catalog, engineered to solve common Information Retrieval (IR) failures in legacy library discovery systems.

## The Problem

Enterprise library discovery platforms (such as Innovative Interfaces Vega) treat queries as rigid literal text strings and rely on basic token matching. This causes two major failures:

1. **Zero-Result Dead Ends:** Natural multi-word queries with modifiers (e.g., `"astro bot ps5"`) fail because hardware platforms or format tags are indexed separately from core titles.
2. **Token Pollution (False Positives):** Broad token matching pulls in completely unrelated records (such as books mentioning words deep within their paragraph descriptions) because the engine lacks field-weighting and precision thresholds.

## The Enterprise Solution

This application implements a professional **Query Understanding (QU)** and **Learning-to-Rank (LTR)** middleware layer inspired by modern e-commerce search architectures:

* **Dynamic Facet Extraction:** Uses regular expressions and token analysis to decouple unstructured text from temporal (years) and hardware/format constraints.
* **Resilient Fallback:** Automatically relaxes strict query strings to prevent zero-result dead ends.
* **Multi-Feature Re-Ranking:** Scores and sorts result candidates dynamically using contextual feature weights (e.g., publication recency and platform boosting) to ensure the most relevant items surface instantly.

## Architecture

* **Frontend:** Responsive, minimalist UI built with modern HTML5, CSS3, and Vanilla JavaScript, deployed statically on Vercel.
* **Backend:** Serverless Python (`api/search.py`) acting as a secure proxy middleware to the Vega ILS API, handling parsing, normalization, and re-ranking in real-time.