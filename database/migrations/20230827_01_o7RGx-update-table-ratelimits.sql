-- update table ratelimits
-- depends: 20230705_02_YP19i-create-table-messages

ALTER TABLE `ratelimits`
    ADD `msg_total` int unsigned NOT NULL DEFAULT '0' COMMENT 'total message counter (never reset)' AFTER `rcpt_counter`,
    ADD `rcpt_total` int unsigned NOT NULL DEFAULT '0' COMMENT 'total recipient counter (never reset)' AFTER `msg_total`;

-- update totals, but don't touch updated_at timestamp
UPDATE `ratelimits` SET `msg_total` = `msg_counter`, `rcpt_total` = `rcpt_counter`, `updated_at` = `updated_at`;
