package com.hopnshoppe.common.exception;

/**
 * Thrown when a requested resource does not exist.
 * Maps to HTTP 404 in {@link GlobalExceptionHandler}.
 *
 * <p>Example usage:
 * <pre>
 * throw new ResourceNotFoundException("User not found: " + email);
 * </pre>
 */
public class ResourceNotFoundException extends RuntimeException {

    public ResourceNotFoundException(String message) {
        super(message);
    }
}
