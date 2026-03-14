package com.hopnshoppe.catalog.service;

import com.hopnshoppe.catalog.event.ProductEventPublisher;
import com.hopnshoppe.catalog.provider.CatalogProvider;
import com.hopnshoppe.common.dto.UnifiedProductDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.Collection;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Orchestrates all registered {@link CatalogProvider} beans in parallel using the
 * <em>Aggregator Pattern</em>, merging their results into a single unified product list.
 *
 * <p>Spring auto-collects every {@code CatalogProvider} bean (AEM, PIM, Legacy SOAP)
 * into the injected list. Adding a new data source only requires implementing the
 * interface and annotating the class with {@code @Component} — no changes here.
 *
 * <p>Provider failures are isolated: a failing provider returns an empty list while
 * the others still contribute, so no single source outage degrades the full catalog.
 */
@Service
public class CatalogOrchestrator {

    private static final Logger logger = LoggerFactory.getLogger(CatalogOrchestrator.class);

    private final List<CatalogProvider> providers;
    private final ProductEventPublisher eventPublisher;

    public CatalogOrchestrator(List<CatalogProvider> providers, ProductEventPublisher eventPublisher) {
        this.providers = providers;
        this.eventPublisher = eventPublisher;
    }

    /**
     * Executes all providers in parallel and merges their results.
     *
     * <p>Each provider runs in its own {@link CompletableFuture} on the common
     * fork-join pool. Exceptions thrown inside a future are caught and logged;
     * the failed provider contributes an empty list to the merge.
     *
     * @return merged list of {@link UnifiedProductDTO} from all providers
     */
    public List<UnifiedProductDTO> fetchAllProducts() {
        List<CompletableFuture<List<UnifiedProductDTO>>> futures = providers.stream()
                .map(provider -> CompletableFuture.supplyAsync(() -> {
                    try {
                        List<UnifiedProductDTO> products = provider.fetchProducts();
                        logger.info("Provider '{}' returned {} products",
                                provider.providerName(), products.size());
                        return products;
                    } catch (Exception e) {
                        logger.warn("Provider '{}' failed — contributing empty list. Cause: {}",
                                provider.providerName(), e.getMessage());
                        return Collections.<UnifiedProductDTO>emptyList();
                    }
                }))
                .collect(Collectors.toList());

        List<UnifiedProductDTO> merged = futures.stream()
                .map(CompletableFuture::join)
                .flatMap(Collection::stream)
                .collect(Collectors.toList());

        logger.info("CatalogOrchestrator merged {} total products from {} providers",
                merged.size(), providers.size());

        eventPublisher.publishAll(merged);

        return merged;
    }
}
