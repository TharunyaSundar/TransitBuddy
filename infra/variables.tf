variable "region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "repo_url" {
  description = "Public git repository the instance clones."
  type        = string
  default     = "https://github.com/TharunyaSundar/TransitBuddy.git"
}

variable "git_ref" {
  description = "Branch, tag or commit to deploy. Changing it replaces the instance."
  type        = string
  default     = "main"
}

variable "env_parameter_name" {
  description = "SSM SecureString holding the bot's .env contents (written by the workflow, not Terraform)."
  type        = string
  default     = "/transitbuddy/env"
}
