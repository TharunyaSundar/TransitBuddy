data "aws_ssm_parameter" "ubuntu_ami" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_caller_identity" "current" {}

# The bot only makes outbound connections (Discord, MongoDB Atlas, LLM API).
# No inbound rules at all; use SSM Session Manager instead of SSH.
resource "aws_security_group" "bot" {
  name_prefix = "transitbuddy-"
  description = "Transit Buddy bot: outbound only"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_iam_role" "bot" {
  name = "transitbuddy-bot"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.bot.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "read_env" {
  name = "read-env-parameter"
  role = aws_iam_role.bot.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${var.env_parameter_name}"
    }]
  })
}

resource "aws_iam_instance_profile" "bot" {
  name = "transitbuddy-bot"
  role = aws_iam_role.bot.name
}

resource "aws_instance" "bot" {
  ami                    = data.aws_ssm_parameter.ubuntu_ami.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.bot.id]
  iam_instance_profile   = aws_iam_instance_profile.bot.name

  associate_public_ip_address = true # needed for outbound traffic in the default VPC (no NAT)

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url           = var.repo_url
    git_ref            = var.git_ref
    region             = var.region
    env_parameter_name = var.env_parameter_name
  })
  user_data_replace_on_change = true # new git_ref or script => fresh instance = redeploy

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name = "transit-buddy-bot"
  }

  depends_on = [aws_iam_role_policy.read_env]
}
