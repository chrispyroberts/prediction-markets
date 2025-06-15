# === BEGIN: connect_to_ec2.ps1 ===
param(
    [string]$PemPath = "C:\Users\chris\OneDrive\Desktop\Programming\ssh keys\AWS Key.pem",
    [string]$Ec2User = "ubuntu",
    [string]$Ec2Host = "ec2-54-84-245-133.compute-1.amazonaws.com"
)

# Set proper permissions on PEM key (read-only for user)
Write-Host "🔐 Fixing permissions on PEM file..."
icacls $PemPath /inheritance:r > $null
icacls $PemPath /grant:r "$($env:USERNAME):(R)" > $null

# SSH into EC2
Write-Host "🌐 Connecting to EC2 instance at $Ec2Host..."
ssh -i $PemPath -N -L 5433:localhost:5432 "$Ec2User@$Ec2Host"
# Check if the SSH command was successful
# === END ===
