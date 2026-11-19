variable "aws_region" {
  description = "AWS region for resources"
  type        = string
}

variable "openai_api_key" {
  description = "OpenAI API key for the researcher agent"
  type        = string
  sensitive   = true
}

variable "afp_api_endpoint" {
  description = "AFP API endpoint from Stage 3"
  type        = string
}

variable "afp_api_key" {
  description = "AFP API key from Stage 3"
  type        = string
  sensitive   = true
}

variable "scheduler_enabled" {
  description = "Enable automated research scheduler"
  type        = bool
  default     = false
}

variable "researcher_image_uri" {
  description = "Full ECR image URI for the researcher Lambda container"
  type        = string
  default     = ""
}

variable "bedrock_region" {
  description = "AWS region used for Bedrock model inference"
  type        = string
  default     = "us-east-1"
}

variable "researcher_model" {
  description = "Bedrock model identifier used by the researcher"
  type        = string
  default     = "bedrock/converse/openai.gpt-oss-120b-1:0"
}

variable "mcp_logging" {
  description = "Set to exact string True to enable researcher MCP logging"
  type        = string
  default     = "False"
}
