# File: legacy.rb - Ruby service
# Ruby is NOT currently supported by DeepDoc.
# This file must appear in coverage as "inventory_only" with language "Ruby".

module LegacyService
  def self.process_order(order_data)
    {
      status: "processed",
      order_id: order_data[:id],
      items: order_data[:items].length
    }
  end

  def self.generate_report(start_date, end_date)
    {
      generated_at: Time.now.iso8601,
      range: "#{start_date}..#{end_date}"
    }
  end
end