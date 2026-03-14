package com.hopnshoppe.catalog.provider;

import com.hopnshoppe.common.dto.UnifiedProductDTO;

import java.util.List;

/**
 * Strategy interface for product data providers.
 *
 * <p>Each implementation encapsulates a specific data source (AEM, PIM, Legacy SOAP).
 * All providers are discovered automatically by {@link com.hopnshoppe.catalog.service.CatalogOrchestrator}
 * and executed in parallel to produce a merged product catalog.
 */
public interface CatalogProvider {

    /**
     * Fetches all available products from this provider's data source.
     *
     * @return list of products mapped to the shared {@link UnifiedProductDTO} contract;
     *         never {@code null} — return an empty list on failure
     */
    List<UnifiedProductDTO> fetchProducts();

    /**
     * Human-readable name used in log messages to identify this provider.
     */
    String providerName();
}
