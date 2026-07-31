def send_email_report(deals):
    """Generates an HTML table for each Product Type and sends it via email securely."""
    sender_email = os.getenv("GMAIL_ADDRESS")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = os.getenv("RECIPIENT_EMAIL")

    if not sender_email or not sender_password or not recipient_email:
        print("\n⚠️ Missing email credentials or recipient email in GitHub Secrets. Skipping email delivery.")
        return

    if not deals:
        print("\n📭 No deals found today to email.")
        return

    print(f"\n📧 Formatting {len(deals)} deals into an email report for {recipient_email}...")

    # Group deals by theme (Product Type)
    grouped_deals = {}
    for deal in deals:
        theme = deal.get("theme", "General LEGO").title()
        if theme not in grouped_deals:
            grouped_deals[theme] = []
        grouped_deals[theme].append(deal)

    # Start building the HTML
    html = """
    <html>
    <head>
    <style>
      body { font-family: Arial, sans-serif; }
      table { border-collapse: collapse; width: 100%; margin-bottom: 30px; }
      th, td { text-align: left; padding: 8px; border: 1px solid #ddd; }
      th { background-color: #f2f2f2; color: #333; }
      a { color: #0066c0; text-decoration: none; font-weight: bold; }
      a:hover { text-decoration: underline; }
      h2 { color: #232f3e; }
      h3 { color: #0066c0; border-bottom: 2px solid #0066c0; padding-bottom: 5px; margin-top: 20px;}
    </style>
    </head>
    <body>
    <h2>Daily LEGO Deals Report</h2>
    <p>Total Deals Found: <strong>{total}</strong></p>
    """.replace("{total}", str(len(deals)))
    
    # Iterate through each group and create a separate table
    for theme, theme_deals in sorted(grouped_deals.items()):
        html += f"<h3>{theme} ({len(theme_deals)} Deals)</h3>"
        html += """
        <table>
          <tr>
            <th>Product Name</th>
            <th>Current</th>
            <th>Original</th>
            <th>Discount</th>
            <th>Shipper</th>
            <th>Seller</th>
            <th>Status Change</th>
            <th>Amazon Link</th>
          </tr>
        """
        
        for deal in theme_deals:
            status = deal.get("status_change", "")
            row_style = ""
            
            # Color coding based on status change
            if status == "New":
                row_style = ' style="background-color: #d4edda;"' # Light Green
            elif status == "Removed":
                row_style = ' style="background-color: #e2e3e5; color: #6c757d;"' # Light Grey
            elif status == "Price Changed":
                row_style = ' style="background-color: #fff3cd;"' # Light Yellow

            html += f"""
          <tr{row_style}>
            <td>{deal.get('title', 'N/A')}</td>
            <td>${deal.get('current_price', 0):.2f}</td>
            <td>${deal.get('original_price', 0):.2f}</td>
            <td style="color: red; font-weight: bold;">{deal.get('discount', 0)}%</td>
            <td>{deal.get('shipper', 'N/A')}</td>
            <td>{deal.get('seller', 'N/A')}</td>
            <td style="font-weight: bold;">{status}</td>
            <td><a href="{deal.get('link', '#')}">View Deal</a></td>
          </tr>
            """
            
        html += """
        </table>
        """

    html += """
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"LEGO Deals Report - {len(deals)} Great Discounts Found!"
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, msg.as_string())
        server.quit()
        print(f"✅ Email successfully sent to {recipient_email} with grouped tables.")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
