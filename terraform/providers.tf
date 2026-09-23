provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project   = "cloud-cost-guardian"
      ManagedBy = "terraform"
      # The scanner protects anything with this tag, including itself.
      cost-guardian-protected = "true"
    }
  }
}
