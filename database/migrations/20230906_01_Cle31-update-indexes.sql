-- update indexes
-- depends: 20230827_01_o7RGx-update-table-ratelimits

ALTER TABLE `ratelimits` RENAME INDEX `idx_sender` TO `ratelimits_sender_unique`;
ALTER TABLE `messages` ADD INDEX `messages_created_at_index` (`created_at`);
