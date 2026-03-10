package com.hopnshoppe.common.exception;

/**
 * Thrown when an operation conflicts with existing state.
 * Maps to HTTP 409 in {@link GlobalExceptionHandler}.
 *
 * <p>Example usage:
 * <pre>
 * throw new ConflictException("Email already registered: " + email);
 * </pre>
 */
public class ConflictException extends RuntimeException {

    public ConflictException(String message) {
        super(message);
    }
}
