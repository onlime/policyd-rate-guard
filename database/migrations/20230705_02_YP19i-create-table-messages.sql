-- Create table messages
-- depends: 20230705_01_MCroB-create-table-ratelimits

CREATE TABLE `messages` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `ratelimit_id` bigint unsigned DEFAULT NULL,
  `sender` varchar(255) NOT NULL COMMENT 'sender address (SASL username)',
  `rcpt_count` int NOT NULL COMMENT 'number of recipients',
  `blocked` tinyint(1) NOT NULL COMMENT 'message was blocked due to reached quota',
  `msgid` varchar(255) DEFAULT NULL COMMENT 'message ID',
  `from_addr` varchar(255) DEFAULT NULL COMMENT 'from address',
  `to_addr` text DEFAULT NULL COMMENT 'to address(es)',
  `cc_addr` text DEFAULT NULL COMMENT 'Cc address(es)',
  `bcc_addr` text DEFAULT NULL COMMENT 'Bcc address(es)',
  `subject` varchar(255) NOT NULL DEFAULT '' COMMENT 'email subject',
  `client_address` varchar(45) NULL DEFAULT NULL COMMENT 'client ip',
  `client_name` varchar(255) NULL DEFAULT NULL COMMENT 'client hostname',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `messages_ratelimit_id_foreign` (`ratelimit_id`),
  CONSTRAINT `messages_ratelimit_id_foreign` FOREIGN KEY (`ratelimit_id`) REFERENCES `ratelimits` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
);
