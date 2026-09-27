# Deploy the built frontend (dist/) to an S3 static website.
# Sidesteps the Amplify app limit; 100% free-tier friendly.
# Usage:  powershell -ExecutionPolicy Bypass -File deploy_s3.ps1
param(
    [string]$Bucket  = "agentsentry-dashboard-273354655941",
    [string]$Region  = "us-east-1",
    [string]$Profile = "agentsentry"
)

$ErrorActionPreference = "Stop"

Write-Host "1/5 Creating bucket $Bucket ..."
# us-east-1 must NOT pass a LocationConstraint.
aws s3api create-bucket --bucket $Bucket --region $Region --profile $Profile 2>$null

Write-Host "2/5 Disabling Block Public Access ..."
aws s3api put-public-access-block --bucket $Bucket --profile $Profile `
    --public-access-block-configuration "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"

Write-Host "3/5 Enabling static website hosting ..."
aws s3 website "s3://$Bucket" --index-document index.html --error-document index.html --profile $Profile

Write-Host "4/5 Applying public-read bucket policy ..."
$policy = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::$Bucket/*"
    }
  ]
}
"@
$policyFile = Join-Path $env:TEMP "agentsentry-bucket-policy.json"
$policy | Out-File -FilePath $policyFile -Encoding ascii
aws s3api put-bucket-policy --bucket $Bucket --policy "file://$policyFile" --profile $Profile
Remove-Item $policyFile -ErrorAction SilentlyContinue

Write-Host "5/5 Uploading dist/ ..."
aws s3 sync dist "s3://$Bucket" --delete --profile $Profile

$url = "http://$Bucket.s3-website-$Region.amazonaws.com"
Write-Host ""
Write-Host "DONE. Public URL:"
Write-Host $url
