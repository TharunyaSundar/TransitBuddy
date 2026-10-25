output "instance_id" {
  value = aws_instance.bot.id
}

output "public_ip" {
  value = aws_instance.bot.public_ip
}

output "connect" {
  description = "Open a shell on the bot (needs the AWS Session Manager plugin)."
  value       = "aws ssm start-session --target ${aws_instance.bot.id} --region ${var.region}"
}

output "logs" {
  value = "sudo journalctl -u transitbuddy -f"
}
