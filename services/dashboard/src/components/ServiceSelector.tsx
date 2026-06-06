import type { ServiceOption } from "../api/types";

interface ServiceSelectorProps {
  services: ServiceOption[];
  selectedServiceId: string;
  onChange: (serviceId: string) => void;
}

export function ServiceSelector({
  services,
  selectedServiceId,
  onChange
}: ServiceSelectorProps) {
  return (
    <label className="field">
      <span>Service</span>
      <select value={selectedServiceId} onChange={(event) => onChange(event.target.value)}>
        {services.map((service) => (
          <option key={service.id} value={service.id}>
            {service.label}
          </option>
        ))}
      </select>
    </label>
  );
}
