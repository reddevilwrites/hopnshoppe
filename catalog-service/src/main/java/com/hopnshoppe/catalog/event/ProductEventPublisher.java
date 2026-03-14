package com.hopnshoppe.catalog.event;

import com.hopnshoppe.common.dto.UnifiedProductDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Publishes {@link UnifiedProductDTO} events to the {@code product-updates} Kafka topic.
 *
 * <p>Each product is keyed by its {@code id} so Kafka partitions events deterministically
 * per product — consumers processing the same partition always see events for the same
 * product in order.
 *
 * <p>Failures are logged but do not propagate: a publish error must never disrupt the
 * aggregation response returned to the caller.
 */
@Component
public class ProductEventPublisher {

    private static final Logger logger = LoggerFactory.getLogger(ProductEventPublisher.class);
    public static final String TOPIC = "product-updates";

    private final KafkaTemplate<String, UnifiedProductDTO> kafkaTemplate;

    public ProductEventPublisher(KafkaTemplate<String, UnifiedProductDTO> kafkaTemplate) {
        this.kafkaTemplate = kafkaTemplate;
    }

    /**
     * Publishes one Kafka event per product. Fire-and-forget with async completion logging.
     */
    public void publishAll(List<UnifiedProductDTO> products) {
        for (UnifiedProductDTO product : products) {
            kafkaTemplate.send(TOPIC, product.getId(), product)
                    .whenComplete((result, ex) -> {
                        if (ex != null) {
                            logger.error("Failed to publish event for product id='{}': {}",
                                    product.getId(), ex.getMessage());
                        } else {
                            logger.debug("Published product id='{}' → topic='{}' partition={}",
                                    product.getId(), TOPIC,
                                    result.getRecordMetadata().partition());
                        }
                    });
        }
    }
}
