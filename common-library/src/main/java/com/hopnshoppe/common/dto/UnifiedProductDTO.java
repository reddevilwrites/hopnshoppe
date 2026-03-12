package com.hopnshoppe.common.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Canonical product representation returned by the Aggregator Pattern in catalog-service.
 *
 * <p>Merges products from two sources:
 * <ul>
 *   <li>{@code "AEM"} — content fragments published from Adobe Experience Manager via GraphQL</li>
 *   <li>{@code "MARKETPLACE"} — products fetched from the DummyJSON external marketplace API</li>
 * </ul>
 *
 * <p>Exposed at {@code GET /products/unified} by catalog-service.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class UnifiedProductDTO {

    /** Unique identifier — SKU for AEM products, string-encoded numeric ID for MARKETPLACE. */
    private String id;

    /** Display name of the product. */
    private String name;

    /** Plain-text product description. */
    private String description;

    /** Product price in the source currency. */
    private double price;

    /** URL of the primary product image or thumbnail. */
    private String imageUrl;

    /** Data origin: {@code "AEM"} or {@code "MARKETPLACE"}. */
    private String source;
}
