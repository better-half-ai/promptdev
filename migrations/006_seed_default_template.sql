-- Seed default template
INSERT INTO system_prompt (name, content, current_version) VALUES 
('default', E'<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\n{{current_message}}<|im_end|>\n<|im_start|>assistant\n', 1)
ON CONFLICT (name) DO NOTHING;
