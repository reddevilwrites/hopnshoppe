package com.hopnshoppe.common.exception;

/**
 * Thrown when a downstream service call fails (e.g. circuit breaker open).
 * Maps to HTTP 503 in {@link GlobalExceptionHandler}.
 *
 * <p>Example usage — Resilience4j fallback method:
 * <pre>
 * public UserDTO createProfileFallback(UserDTO dto, Throwable t) {
 *     throw new ServiceUnavailableException("user-service is unavailable", t);
 * }
 * </pre>
 */
public class ServiceUnavailableException extends RuntimeException {

    public ServiceUnavailableException(String message) {
        super(message);
    }

    public ServiceUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
