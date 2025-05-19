package com.wknd.spring.client.config_client.filter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.IOException;

public class ApiKeyFilter extends OncePerRequestFilter {

    private final String expectedApiKey;

    public ApiKeyFilter(String expectedApiKey) {
        this.expectedApiKey = expectedApiKey;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {

        String path = request.getRequestURI();

        // Only filter /products (and sub-paths), skip /api/products
        if (path.startsWith("/products")) {
            String apiKey = request.getHeader("X-API-KEY");
            System.out.println("=== FILTER TRIGGERED: " + request.getRequestURI());
            System.out.println("Incoming: " + apiKey + ", Expected: " + expectedApiKey);

            if (expectedApiKey.equals(apiKey)) {
                filterChain.doFilter(request, response);
            } else {
                response.sendError(HttpServletResponse.SC_UNAUTHORIZED, "Invalid API key");
            }
        } else {
            // Let other requests pass (e.g. /api/products)
            filterChain.doFilter(request, response);
        }
    }
}
