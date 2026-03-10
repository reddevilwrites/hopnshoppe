package com.hopnshoppe.common.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Standard error response envelope returned by GlobalExceptionHandler.
 *
 * <p>All services that include common-library will emit errors in this shape:
 * <pre>
 * {
 *   "status":  404,
 *   "error":   "Not Found",
 *   "message": "User not found: user@example.com",
 *   "path":    "/account/me",
 *   "timestamp": "2026-03-09T14:30:00"
 * }
 * </pre>
 */
@Data
@Builder
public class ApiErrorDTO {

    /** HTTP status code (e.g. 400, 404, 503). */
    private int status;

    /** HTTP reason phrase (e.g. "Not Found", "Service Unavailable"). */
    private String error;

    /** Human-readable description from the exception message. */
    private String message;

    /** Request URI that produced the error, aiding log correlation. */
    private String path;

    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd'T'HH:mm:ss")
    @Builder.Default
    private LocalDateTime timestamp = LocalDateTime.now();
}
