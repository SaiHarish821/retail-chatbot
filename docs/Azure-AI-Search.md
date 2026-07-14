# Azure AI Search

## 1. Overview

The Retail AI Assistant uses an **in-memory product search engine** implemented in `backend/agents/tools.py` rather than Azure AI Search as an external service. The search algorithm provides rich product discovery with synonym resolution, multi-field matching, relevance scoring, dietary filtering, and proximity-based store ranking.

> **Note:** While `azure-search-documents` is listed in `requirements.txt` for future integration, the current implementation uses a custom in-memory search over the SQLite/PostgreSQL product catalog.

## 2. Search Architecture

```mermaid
graph TD
    Query["User Query<br/>'organic milk'"] --> Synonyms["Synonym Resolution"]
    Synonyms --> Tokenize["Tokenise Query"]
    Tokenize --> Score["Score All Products"]
    
    subgraph "Scoring Engine"
        NameExact["Name Exact Match<br/>+150 points"]
        NamePartial["Name Partial Match<br/>+100 points"]
        NameWord["Word in Name<br/>+40 points"]
        Category["Category Match<br/>+30 points"]
        Tag["Tag Match<br/>+20 points"]
        Description["Description Match<br/>+10 points"]
    end
    
    Score --> NameExact
    Score --> NamePartial
    Score --> NameWord
    Score --> Category
    Score --> Tag
    Score --> Description
    
    NameExact --> Filter["Apply Filters"]
    NamePartial --> Filter
    NameWord --> Filter
    Category --> Filter
    Tag --> Filter
    Description --> Filter
    
    Filter --> Sort["Sort & Rank"]
    Sort --> Format["Format Results"]
    Format --> Output["Search Results"]
```

## 3. Synonym Resolution

The search engine maps common aliases and misspellings to canonical product terms:

| Input Term | Resolves To |
|-----------|-------------|
| `semi-skimmed milk`, `skimmed milk` | `milk` |
| `wholemeal bread`, `white bread`, `loaf` | `bread` |
| `mince`, `beef mince` | `beef` |
| `fish fingers` | `fish` |
| `chips`, `frozen chips` | `potato` |
| `cola`, `soda`, `pop` | `drink` |
| `biscuits`, `cookies` | `biscuit` |
| `nappies`, `nappy` | `baby` |
| `washing up liquid`, `dish soap` | `dishwasher` |
| `loo roll`, `toilet tissue` | `toilet paper` |

## 4. Search Flow

```mermaid
sequenceDiagram
    participant Agent as Specialist Agent
    participant Tool as search_products()
    participant DB as Database
    participant Scorer as Scoring Engine

    Agent->>Tool: search_products(query="organic milk", category=None, dietary_filters=["organic"])
    Tool->>DB: load_db_inventory_data()
    DB-->>Tool: {inventory: [...], metadata: {stores: {...}}}

    Tool->>Tool: Resolve synonyms("organic milk")
    Tool->>Tool: Tokenise ["organic", "milk"]

    loop Each product in inventory
        Tool->>Scorer: Calculate relevance score
        Scorer->>Scorer: Check name match (+150/+100/+40)
        Scorer->>Scorer: Check category match (+30)
        Scorer->>Scorer: Check tag match (+20)
        Scorer->>Scorer: Check description match (+10)
        Scorer-->>Tool: score = 190 (e.g., name partial + tag)
    end

    Tool->>Tool: Filter: score > 0
    Tool->>Tool: Filter: dietary_filters (organic=1)
    Tool->>Tool: Filter: category (if specified)
    Tool->>Tool: Filter: is_on_promotion (if specified)

    Tool->>Tool: Sort by recommendation score
    Note right of Tool: Sort order:<br/>1. In-stock first<br/>2. Popularity score desc<br/>3. Best seller flag<br/>4. Customer rating desc<br/>5. Promotional items

    Tool->>Tool: Limit results (default 5)
    Tool->>Tool: Format as markdown string

    Tool-->>Agent: "Found 2 matching products:\n1. Organic Whole Milk 2L..."
```

## 5. Filtering Capabilities

### Category Filter

Products are filtered by exact category match:
- Dairy, Bakery, Produce, Pantry, Drinks, Fresh Meat & Fish, Confectionery, Breakfast, Household

### Dietary Filters

| Filter | Database Column | Description |
|--------|----------------|-------------|
| `organic` | `organic` | Certified organic products |
| `vegan` | `vegan` | No animal products |
| `gluten_free` | `gluten_free` | No gluten-containing ingredients |
| `sugar_free` | `sugar_free` | No added or natural sugars |
| `high_protein` | `high_protein` | High protein content |
| `lactose_free` | `lactose_free` | No dairy/lactose |
| `healthy_choice` | `healthy_choice` | Healthy/nutritious items |

### Sorting Options

| Sort Key | Behaviour |
|----------|-----------|
| `price_asc` | Lowest price first |
| `price_desc` | Highest price first |
| `rating` | Highest customer rating first |
| `popularity` | Highest popularity score first |

## 6. Stock Check

The `check_stock` tool provides store-level inventory information:

```mermaid
flowchart TD
    Input["check_stock(product_name, store_name)"] --> LoadDB["Load inventory data"]
    LoadDB --> FuzzyMatch["Fuzzy-match product name"]
    FuzzyMatch --> Found{Product found?}
    
    Found -->|No| NotFound["Return 'Product not found'"]
    Found -->|Yes| StoreFilter{store_name<br/>specified?}
    
    StoreFilter -->|Yes| SingleStore["Filter to matching store"]
    StoreFilter -->|No| AllStores["Show all stores"]
    
    SingleStore --> Proximity["Calculate Haversine distance<br/>from customer postcode"]
    AllStores --> Proximity
    
    Proximity --> SortStores["Sort stores by distance"]
    SortStores --> Format["Format: store, quantity, aisle, price"]
    Format --> Output["Stock results string"]
```

### Proximity Calculation

The Haversine formula calculates distance between the customer's postcode coordinates and each store:

```python
def _haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))
```

### Postcode Geocoding

A built-in mapping converts London postcodes to lat/lng coordinates:

| Postcode Prefix | Latitude | Longitude | Area |
|----------------|----------|-----------|------|
| SW1A | 51.5014 | -0.1419 | Westminster |
| N1 | 51.5362 | -0.1072 | Islington |
| NW1 | 51.5392 | -0.1426 | Camden |
| E15 | 51.5416 | 0.0024 | Stratford |

## 7. Promotion Retrieval

The `get_active_promotions` tool queries the promotions table:

```mermaid
flowchart TD
    Input["get_active_promotions()"] --> LoadDB["Query promotions table"]
    LoadDB --> FormatList["Format each promotion"]
    
    subgraph "Promotion Fields"
        Name["Offer Name"]
        Discount["Discount (e.g., 20% OFF)"]
        Code["Coupon Code"]
        Expiry["Expiry Date"]
        Categories["Applicable Categories"]
        Products["Applicable Products"]
        Loyalty["Loyalty Requirement"]
    end
    
    FormatList --> Output["Formatted promotions list"]
```

### Seed Promotions

| Offer ID | Name | Discount | Code | Categories | Loyalty Req |
|----------|------|----------|------|------------|-------------|
| OFF-001 | 20% OFF Dairy | 20% OFF | DAIRY20 | Dairy | None |
| OFF-002 | Weekend Organic Sale | 15% OFF | ORGANIC15 | (specific products) | None |
| OFF-003 | Gold Member Special | 10% OFF | GOLD10 | All | Gold |
| OFF-004 | Weekend Offer | 10% OFF | WEEKEND10 | Produce, Bakery | None |
| OFF-005 | Buy 1 Get 1 (BOGO) | BOGO | BOGO | (specific products) | None |

## 8. Product Decoration

When products are seeded into the database, the `decorate_product()` function generates rich metadata deterministically using MD5 hashing:

```mermaid
flowchart TD
    Product["Raw Product"] --> Hash["MD5 hash of product_id"]
    Hash --> Rating["Rating: 4.0 - 4.9"]
    Hash --> Reviews["Reviews: 120 - 2400"]
    Hash --> Popularity["Popularity: 60 - 99"]
    Hash --> BestSeller["Best Seller: pop > 82"]
    Hash --> StoreRec["Store Recommended: h%3"]
    Hash --> StaffPick["Staff Pick: h%8"]
    
    Product --> DietCheck["Dietary Analysis"]
    DietCheck --> Organic["Organic: 'organic' in name"]
    DietCheck --> Vegan["Vegan: no meat/dairy/eggs"]
    DietCheck --> GlutenFree["Gluten Free: no wheat"]
    DietCheck --> SugarFree["Sugar Free: no sweets"]
    DietCheck --> HighProtein["High Protein: meat/eggs/cheese"]
    DietCheck --> LactoseFree["Lactose Free: no dairy"]
    
    Product --> Discount["Discount Calculation"]
    Discount --> PromoPct["10%, 20%, or 30% OFF"]
    Discount --> OldPrice["Calculate old price"]
    
    Product --> FBT["Frequently Bought Together"]
    FBT --> FBTList["Context-specific pairs"]
```

## 9. Future: Azure AI Search Integration

The `azure-search-documents` dependency is included for future vector/semantic search capabilities:

```mermaid
graph LR
    subgraph "Current"
        InMemory["In-Memory<br/>Keyword Search"]
    end
    
    subgraph "Future"
        AzSearch["Azure AI Search"]
        VectorIndex["Vector Index<br/>(Embeddings)"]
        SemanticSearch["Semantic Ranking"]
        HybridSearch["Hybrid Search<br/>(Keyword + Vector)"]
    end
    
    InMemory -.->|"Migration Path"| AzSearch
    AzSearch --> VectorIndex
    AzSearch --> SemanticSearch
    AzSearch --> HybridSearch
```

Potential benefits of migrating to Azure AI Search:
- **Semantic understanding** — "healthy snacks" matches products without keyword overlap
- **Vector search** — Embedding-based similarity across product descriptions
- **Faceted navigation** — Category/brand/dietary facets
- **Relevance tuning** — Configurable scoring profiles
- **Scale** — Handles millions of products vs. current in-memory approach
