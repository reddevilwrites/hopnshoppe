package com.hopnshoppe.catalog.provider;

import com.hopnshoppe.common.dto.UnifiedProductDTO;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.Collections;
import java.util.List;

/**
 * {@link CatalogProvider} implementation that simulates a Legacy SOAP-based
 * product catalog integration.
 *
 * <p>In a real deployment this would parse XML from a SOAP endpoint (e.g. via
 * JAX-WS or Spring-WS). Here the SOAP response is mocked with hardcoded products
 * so the orchestration and circuit-breaker wiring can be exercised without an
 * actual SOAP server.
 *
 * <p>Protected by the {@code legacysoap} Resilience4j circuit breaker. When the
 * circuit is open (or the call throws), {@link #fetchProductsFallback(Throwable)}
 * is invoked and returns an empty list — preserving availability for AEM and PIM
 * products.
 *
 * <p><strong>AOP note:</strong> The {@code @CircuitBreaker} annotation is processed
 * by a Spring AOP proxy. Because {@link com.hopnshoppe.catalog.service.CatalogOrchestrator}
 * calls this bean through the {@link CatalogProvider} interface, the proxy intercepts
 * every call correctly — self-invocation limitations do not apply here.
 */
@Component
public class LegacySoapCatalogProvider implements CatalogProvider {

    private static final Logger logger = LoggerFactory.getLogger(LegacySoapCatalogProvider.class);

    @Override
    public String providerName() {
        return "LEGACY_SOAP";
    }

    @Override
    @CircuitBreaker(name = "legacysoap", fallbackMethod = "fetchProductsFallback")
    public List<UnifiedProductDTO> fetchProducts() {
        logger.debug("Fetching products from Legacy SOAP provider");
        return buildMockSoapProducts();
    }

    /**
     * Resilience4j fallback invoked when the {@code legacysoap} circuit opens
     * or the SOAP call throws any exception.
     */
    List<UnifiedProductDTO> fetchProductsFallback(Throwable t) {
        logger.warn("Legacy SOAP circuit breaker activated — returning empty list. Cause: {}", t.getMessage());
        return Collections.emptyList();
    }

    /**
     * Simulates a parsed SOAP response containing legacy catalog products.
     * Replace with real JAX-WS / Spring-WS deserialization in production.
     */
    private List<UnifiedProductDTO> buildMockSoapProducts() {
        return List.of(
                UnifiedProductDTO.builder()
                        .id("SOAP-001")
                        .name("Legacy Wireless Headset Pro")
                        .description("Enterprise-grade wireless headset sourced from the legacy SOAP catalog.")
                        .price(129.99)
                        .imageUrl("https://dummyjson.com/icon/soap001/150")
                        .source("LEGACY")
                        .build(),
                UnifiedProductDTO.builder()
                        .id("SOAP-002")
                        .name("Legacy USB-C Hub 7-Port")
                        .description("High-speed USB-C hub with 7 ports sourced from the legacy SOAP catalog.")
                        .price(59.99)
                        .imageUrl("https://dummyjson.com/icon/soap002/150")
                        .source("LEGACY")
                        .build(),
                UnifiedProductDTO.builder()
                        .id("SOAP-003")
                        .name("Legacy Mechanical Keyboard TKL")
                        .description("Tenkeyless mechanical keyboard sourced from the legacy SOAP catalog.")
                        .price(89.99)
                        .imageUrl("https://dummyjson.com/icon/soap003/150")
                        .source("LEGACY")
                        .build()
        );
    }
}
