-- Create Table ratelimits
-- depends: 

CREATE TABLE `ratelimits` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `sender` varchar(255) NOT NULL COMMENT 'sender address (SASL username)',
  `quota` int unsigned NOT NULL DEFAULT '1000' COMMENT 'current daily recipient quota (can be raised temporarily)',
  `quota_reset` int unsigned NOT NULL DEFAULT '1000' COMMENT 'default daily recipient quota (used for nightly cleanup)',
  `quota_locked` tinyint(1) NOT NULL DEFAULT '0' COMMENT 'prevent recipient quota override by user (Airpane)',
  `msg_counter` int unsigned NOT NULL DEFAULT '0' COMMENT 'current message counter',
  `rcpt_counter` int unsigned NOT NULL DEFAULT '0' COMMENT 'current recipient counter',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_sender` (`sender`)
);
