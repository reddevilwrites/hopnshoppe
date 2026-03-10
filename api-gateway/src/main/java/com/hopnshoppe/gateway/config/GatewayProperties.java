package com.hopnshoppe.gateway.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;

/**
 * Externalised gateway configuration bound from {@code application.yml}.
 *
 * <pre>
 * gateway:
 *   public-paths:
 *     - /api/auth/login
 *     - /api/auth/signup
 * </pre>
 *
 * <p>Adding a path here exempts it from JWT validation without any code change.
 * Activated via {@code @EnableConfigurationProperties(GatewayProperties.class)}
 * in {@link com.hopnshoppe.gateway.ApiGatewayApplication}.
 */
@Data
@ConfigurationProperties(prefix = "gateway")
public class GatewayProperties {

    /**
     * Paths that bypass JWT validation.
     * Matched as prefix — {@code /api/auth} covers {@code /api/auth/login},
     * {@code /api/auth/signup}, etc.
     */
    private List<String> publicPaths = List.of();
}
