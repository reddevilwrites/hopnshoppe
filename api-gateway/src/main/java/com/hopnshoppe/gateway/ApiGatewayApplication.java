package com.hopnshoppe.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;

import com.hopnshoppe.gateway.config.GatewayProperties;

/**
 * HopNShoppe API Gateway.
 *
 * <p>Single ingress point for all external traffic. Responsibilities:
 * <ul>
 *   <li>JWT validation via {@link filter.JwtAuthenticationFilter} before any route is resolved</li>
 *   <li>Service-discovery-aware routing via Eureka ({@code lb://service-name})</li>
 *   <li>Path rewriting so downstream services are unaware of the /api prefix</li>
 * </ul>
 *
 * <p>Routes are declared in {@code application.yml}. The gateway is stateless —
 * no database, no session — purely reactive (Netty + Project Reactor).
 */
@SpringBootApplication
@EnableDiscoveryClient
@EnableConfigurationProperties(GatewayProperties.class)
public class ApiGatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(ApiGatewayApplication.class, args);
    }
}
