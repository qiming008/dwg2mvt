export interface CoordinateSystemOption {
  dictCode: string
  dictName: string
}

type CoordinateSystemSpec = CoordinateSystemOption

const zoneName = (prefix: string, degree: number, zone: number) =>
  `${prefix} ${degree}度带 ${zone}带号`

const cmName = (prefix: string, degree: number, cm: number) =>
  `${prefix} ${degree}度带 中央经线 ${cm}`

const zoneSpecs = (
  startCode: number,
  prefix: string,
  degree: number,
  zones: number[],
): CoordinateSystemSpec[] =>
  zones.map((zone, offset) => ({
    dictCode: String(startCode + offset),
    dictName: zoneName(prefix, degree, zone),
  }))

const cmSpecs = (
  startCode: number,
  prefix: string,
  degree: number,
  cms: number[],
): CoordinateSystemSpec[] =>
  cms.map((cm, offset) => ({
    dictCode: String(startCode + offset),
    dictName: cmName(prefix, degree, cm),
  }))

export const coordinateSystemOptions: CoordinateSystemOption[] = [
  ...zoneSpecs(2327, '西安80坐标系', 6, Array.from({ length: 11 }, (_, i) => i + 13)),
  ...cmSpecs(2338, '西安80坐标系', 6, Array.from({ length: 11 }, (_, i) => 75 + i * 6)),
  ...zoneSpecs(2349, '西安80坐标系', 3, Array.from({ length: 21 }, (_, i) => i + 25)),
  ...cmSpecs(2370, '西安80坐标系', 3, Array.from({ length: 21 }, (_, i) => 75 + i * 3)),
  ...zoneSpecs(21413, '北京54坐标系', 6, Array.from({ length: 11 }, (_, i) => i + 13)),
  ...cmSpecs(21473, '北京54坐标系', 6, Array.from({ length: 11 }, (_, i) => 75 + i * 6)),
  ...zoneSpecs(2401, '北京54坐标系', 3, Array.from({ length: 21 }, (_, i) => i + 25)),
  ...cmSpecs(2422, '北京54坐标系', 3, Array.from({ length: 21 }, (_, i) => 75 + i * 3)),
  ...zoneSpecs(4491, '国家2000坐标系', 6, Array.from({ length: 11 }, (_, i) => i + 13)),
  ...cmSpecs(4502, '国家2000坐标系', 6, Array.from({ length: 11 }, (_, i) => 75 + i * 6)),
  ...zoneSpecs(4513, '国家2000坐标系', 3, Array.from({ length: 21 }, (_, i) => i + 25)),
  ...cmSpecs(4534, '国家2000坐标系', 3, Array.from({ length: 21 }, (_, i) => 75 + i * 3)),
]
