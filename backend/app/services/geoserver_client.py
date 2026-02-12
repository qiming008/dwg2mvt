# -*- coding: utf-8 -*-
"""通过 GeoServer REST API 发布 GeoPackage 为 MVT/WMTS 图层"""
import base64
from pathlib import Path
import xml.etree.ElementTree as ET

import httpx

from app.config import settings


def _auth_headers() -> dict:
    raw = f"{settings.geoserver_user}:{settings.geoserver_password}"
    token = base64.b64encode(raw.encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _rest(url_path: str) -> str:
    base = settings.geoserver_url.rstrip("/")
    return f"{base}/rest/{url_path}"


DWG_SLD = """<?xml version="1.0" encoding="ISO-8859-1"?>
<StyledLayerDescriptor version="1.0.0" 
    xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd" 
    xmlns="http://www.opengis.net/sld" 
    xmlns:ogc="http://www.opengis.net/ogc" 
    xmlns:xlink="http://www.w3.org/1999/xlink" 
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer>
    <Name>dwg_generic_style</Name>
    <UserStyle>
      <Title>Generic DWG Style</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>Polygon</Name>
          <Filter>
             <Or>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>Polygon</Literal>
               </PropertyIsEqualTo>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>MultiPolygon</Literal>
               </PropertyIsEqualTo>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>GeometryCollection</Literal>
               </PropertyIsEqualTo>
             </Or>
          </Filter>
          <PolygonSymbolizer>
            <Fill>
              <CssParameter name="fill">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>fill_color</PropertyName></ogc:Function>
                   <ogc:Literal>#aaaaaa</ogc:Literal>
                   <PropertyName>fill_color</PropertyName>
                </ogc:Function>
              </CssParameter>
              <CssParameter name="fill-opacity">0.3</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>line_color</PropertyName></ogc:Function>
                   <ogc:Literal>#555555</ogc:Literal>
                   <PropertyName>line_color</PropertyName>
                </ogc:Function>
              </CssParameter>
              <CssParameter name="stroke-width">1</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
        <Rule>
          <Name>Line</Name>
          <Filter>
             <Or>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>LineString</Literal>
               </PropertyIsEqualTo>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>MultiLineString</Literal>
               </PropertyIsEqualTo>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>GeometryCollection</Literal>
               </PropertyIsEqualTo>
             </Or>
          </Filter>
          <LineSymbolizer>
            <Stroke>
              <CssParameter name="stroke">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>line_color</PropertyName></ogc:Function>
                   <ogc:Literal>#333333</ogc:Literal>
                   <PropertyName>line_color</PropertyName>
                </ogc:Function>
              </CssParameter>
              <CssParameter name="stroke-width">1</CssParameter>
            </Stroke>
          </LineSymbolizer>
        </Rule>
        <Rule>
          <Name>Text</Name>
          <Filter>
             <PropertyIsNotEqualTo>
                <PropertyName>Text</PropertyName>
                <Literal></Literal>
             </PropertyIsNotEqualTo>
          </Filter>
          <TextSymbolizer uom="http://www.opengeospatial.org/se/units/metre">
            <Label>
              <ogc:Function name="if_then_else">
                 <ogc:Function name="isNull"><PropertyName>text_content</PropertyName></ogc:Function>
                 <PropertyName>Text</PropertyName>
                 <PropertyName>text_content</PropertyName>
              </ogc:Function>
            </Label>
            <Font>
              <CssParameter name="font-family">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>text_font</PropertyName></ogc:Function>
                   <ogc:Literal>SimSun, Microsoft YaHei, Arial, sans-serif</ogc:Literal>
                   <PropertyName>text_font</PropertyName>
                </ogc:Function>
              </CssParameter>
              <CssParameter name="font-size">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>text_size</PropertyName></ogc:Function>
                   <ogc:Literal>12</ogc:Literal>
                   <ogc:Function name="if_then_else">
                       <ogc:Function name="lessThan"><PropertyName>text_size</PropertyName><ogc:Literal>0.1</ogc:Literal></ogc:Function>
                       <ogc:Literal>0.1</ogc:Literal>
                       <PropertyName>text_size</PropertyName>
                   </ogc:Function>
                </ogc:Function>
              </CssParameter>
              <CssParameter name="font-style">normal</CssParameter>
              <CssParameter name="font-weight">normal</CssParameter>
            </Font>
            <LabelPlacement>
              <PointPlacement>
                <AnchorPoint>
                  <AnchorPointX>
                    <ogc:Function name="if_then_else">
                       <ogc:Function name="isNull"><PropertyName>anchor_x</PropertyName></ogc:Function>
                       <ogc:Literal>0.0</ogc:Literal>
                       <PropertyName>anchor_x</PropertyName>
                    </ogc:Function>
                  </AnchorPointX>
                  <AnchorPointY>
                    <ogc:Function name="if_then_else">
                       <ogc:Function name="isNull"><PropertyName>anchor_y</PropertyName></ogc:Function>
                       <ogc:Literal>0.0</ogc:Literal>
                       <PropertyName>anchor_y</PropertyName>
                    </ogc:Function>
                  </AnchorPointY>
                </AnchorPoint>
                <Rotation>
                   <ogc:Function name="if_then_else">
                      <ogc:Function name="isNull"><PropertyName>text_angle</PropertyName></ogc:Function>
                      <ogc:Function name="if_then_else">
                          <ogc:Function name="isNull"><PropertyName>rotation</PropertyName></ogc:Function>
                          <ogc:Literal>0.0</ogc:Literal>
                          <PropertyName>rotation</PropertyName>
                      </ogc:Function>
                      <PropertyName>text_angle</PropertyName>
                   </ogc:Function>
                </Rotation>
              </PointPlacement>
            </LabelPlacement>
            <Fill>
              <CssParameter name="fill">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>text_color</PropertyName></ogc:Function>
                   <ogc:Function name="if_then_else">
                       <ogc:Function name="isNull"><PropertyName>line_color</PropertyName></ogc:Function>
                       <ogc:Literal>#FFFFFF</ogc:Literal>
                       <PropertyName>line_color</PropertyName>
                   </ogc:Function>
                   <PropertyName>text_color</PropertyName>
                </ogc:Function>
              </CssParameter>
            </Fill>
            <VendorOption name="maxDisplacement">20</VendorOption>
            <VendorOption name="partials">true</VendorOption>
          <VendorOption name="conflictResolution">false</VendorOption>
        </TextSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
"""

DWG_RASTER_SLD = """<?xml version="1.0" encoding="ISO-8859-1"?>
<StyledLayerDescriptor version="1.0.0" 
    xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd" 
    xmlns="http://www.opengis.net/sld" 
    xmlns:ogc="http://www.opengis.net/ogc" 
    xmlns:xlink="http://www.w3.org/1999/xlink" 
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer>
    <Name>dwg_raster_style</Name>
    <UserStyle>
      <Title>DWG Raster Style</Title>
      <FeatureTypeStyle>
        <!-- Polygons: Transparent Fill (to avoid blue fill), Colored Outline -->
        <Rule>
          <Name>Polygon</Name>
          <Filter>
             <Or>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>Polygon</Literal>
               </PropertyIsEqualTo>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>MultiPolygon</Literal>
               </PropertyIsEqualTo>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>GeometryCollection</Literal>
               </PropertyIsEqualTo>
             </Or>
          </Filter>
          <PolygonSymbolizer>
            <!-- Transparent Fill -->
            <Fill>
              <CssParameter name="fill">#000000</CssParameter>
              <CssParameter name="fill-opacity">0.0</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>line_color</PropertyName></ogc:Function>
                   <ogc:Literal>#555555</ogc:Literal>
                   <PropertyName>line_color</PropertyName>
                </ogc:Function>
              </CssParameter>
              <CssParameter name="stroke-width">1</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
        <!-- Lines -->
        <Rule>
          <Name>Line</Name>
          <Filter>
             <Or>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>LineString</Literal>
               </PropertyIsEqualTo>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>MultiLineString</Literal>
               </PropertyIsEqualTo>
               <PropertyIsEqualTo>
                  <Function name="geometryType"><PropertyName>geom</PropertyName></Function>
                  <Literal>GeometryCollection</Literal>
               </PropertyIsEqualTo>
             </Or>
          </Filter>
          <LineSymbolizer>
            <Stroke>
              <CssParameter name="stroke">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>line_color</PropertyName></ogc:Function>
                   <ogc:Literal>#FFFFFF</ogc:Literal>
                   <PropertyName>line_color</PropertyName>
                </ogc:Function>
              </CssParameter>
              <CssParameter name="stroke-width">1</CssParameter>
            </Stroke>
          </LineSymbolizer>
        </Rule>
        <!-- Text with specific size (Ground Units) -->
        <Rule>
          <Name>Text_Ground</Name>
          <Filter>
             <And>
               <PropertyIsNotEqualTo>
                  <PropertyName>Text</PropertyName>
                  <Literal></Literal>
               </PropertyIsNotEqualTo>
               <Not><PropertyIsNull><PropertyName>text_size</PropertyName></PropertyIsNull></Not>
             </And>
          </Filter>
          <TextSymbolizer uom="http://www.opengeospatial.org/se/units/metre">
            <Label>
              <ogc:Function name="if_then_else">
                 <ogc:Function name="isNull"><PropertyName>text_content</PropertyName></ogc:Function>
                 <PropertyName>Text</PropertyName>
                 <PropertyName>text_content</PropertyName>
              </ogc:Function>
            </Label>
            <Font>
              <CssParameter name="font-family">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>text_font</PropertyName></ogc:Function>
                   <ogc:Literal>SimSun, Microsoft YaHei, Arial, sans-serif</ogc:Literal>
                   <PropertyName>text_font</PropertyName>
                </ogc:Function>
              </CssParameter>
              <CssParameter name="font-size">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>text_size</PropertyName></ogc:Function>
                   <ogc:Literal>1.0</ogc:Literal>
                   <ogc:Function name="if_then_else">
                       <ogc:Function name="lessThan"><PropertyName>text_size</PropertyName><ogc:Literal>0.001</ogc:Literal></ogc:Function>
                       <ogc:Literal>0.001</ogc:Literal>
                       <PropertyName>text_size</PropertyName>
                   </ogc:Function>
                </ogc:Function>
              </CssParameter>
              <CssParameter name="font-style">normal</CssParameter>
              <CssParameter name="font-weight">normal</CssParameter>
            </Font>
            <LabelPlacement>
              <PointPlacement>
                <AnchorPoint>
                  <AnchorPointX>
                    <ogc:Function name="if_then_else">
                       <ogc:Function name="isNull"><PropertyName>anchor_x</PropertyName></ogc:Function>
                       <ogc:Literal>0.0</ogc:Literal>
                       <PropertyName>anchor_x</PropertyName>
                    </ogc:Function>
                  </AnchorPointX>
                  <AnchorPointY>
                    <ogc:Function name="if_then_else">
                       <ogc:Function name="isNull"><PropertyName>anchor_y</PropertyName></ogc:Function>
                       <ogc:Literal>0.0</ogc:Literal>
                       <PropertyName>anchor_y</PropertyName>
                    </ogc:Function>
                  </AnchorPointY>
                </AnchorPoint>
                <Rotation>
                   <ogc:Function name="if_then_else">
                      <ogc:Function name="isNull"><PropertyName>text_angle</PropertyName></ogc:Function>
                      <ogc:Function name="if_then_else">
                      <ogc:Function name="isNull"><PropertyName>rotation</PropertyName></ogc:Function>
                      <ogc:Literal>0.0</ogc:Literal>
                      <PropertyName>rotation</PropertyName>
                  </ogc:Function>
                      <PropertyName>text_angle</PropertyName>
                   </ogc:Function>
                </Rotation>
              </PointPlacement>
            </LabelPlacement>
            <Fill>
              <CssParameter name="fill">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>text_color</PropertyName></ogc:Function>
                   <ogc:Function name="if_then_else">
                       <ogc:Function name="isNull"><PropertyName>line_color</PropertyName></ogc:Function>
                       <ogc:Literal>#FFFFFF</ogc:Literal>
                       <PropertyName>line_color</PropertyName>
                   </ogc:Function>
                   <PropertyName>text_color</PropertyName>
                </ogc:Function>
              </CssParameter>
            </Fill>
            <VendorOption name="maxDisplacement">400</VendorOption>
            <VendorOption name="partials">true</VendorOption>
            <VendorOption name="conflictResolution">false</VendorOption>
            <VendorOption name="spaceAround">-1</VendorOption>
          </TextSymbolizer>
        </Rule>

        <!-- Text default (Screen Units) -->
        <Rule>
          <Name>Text_Screen</Name>
          <Filter>
             <And>
               <PropertyIsNotEqualTo>
                  <PropertyName>Text</PropertyName>
                  <Literal></Literal>
               </PropertyIsNotEqualTo>
               <PropertyIsNull><PropertyName>text_size</PropertyName></PropertyIsNull>
             </And>
          </Filter>
          <TextSymbolizer>
            <Label>
              <ogc:Function name="if_then_else">
                 <ogc:Function name="isNull"><PropertyName>text_content</PropertyName></ogc:Function>
                 <PropertyName>Text</PropertyName>
                 <PropertyName>text_content</PropertyName>
              </ogc:Function>
            </Label>
            <Font>
              <CssParameter name="font-family">SimSun, Microsoft YaHei, Arial, sans-serif</CssParameter>
              <CssParameter name="font-size">12</CssParameter>
              <CssParameter name="font-style">normal</CssParameter>
              <CssParameter name="font-weight">normal</CssParameter>
            </Font>
            <LabelPlacement>
              <PointPlacement>
                <AnchorPoint>
                  <AnchorPointX>
                    <ogc:Function name="if_then_else">
                       <ogc:Function name="isNull"><PropertyName>anchor_x</PropertyName></ogc:Function>
                       <ogc:Literal>0.0</ogc:Literal>
                       <PropertyName>anchor_x</PropertyName>
                    </ogc:Function>
                  </AnchorPointX>
                  <AnchorPointY>
                    <ogc:Function name="if_then_else">
                       <ogc:Function name="isNull"><PropertyName>anchor_y</PropertyName></ogc:Function>
                       <ogc:Literal>0.0</ogc:Literal>
                       <PropertyName>anchor_y</PropertyName>
                    </ogc:Function>
                  </AnchorPointY>
                </AnchorPoint>
                <Rotation>
                   <ogc:Function name="if_then_else">
                      <ogc:Function name="isNull"><PropertyName>text_angle</PropertyName></ogc:Function>
                      <ogc:Function name="if_then_else">
                          <ogc:Function name="isNull"><PropertyName>rotation</PropertyName></ogc:Function>
                          <ogc:Literal>0.0</ogc:Literal>
                          <PropertyName>rotation</PropertyName>
                      </ogc:Function>
                      <PropertyName>text_angle</PropertyName>
                   </ogc:Function>
                </Rotation>
              </PointPlacement>
            </LabelPlacement>
            <Fill>
              <CssParameter name="fill">
                <ogc:Function name="if_then_else">
                   <ogc:Function name="isNull"><PropertyName>text_color</PropertyName></ogc:Function>
                   <ogc:Function name="if_then_else">
                       <ogc:Function name="isNull"><PropertyName>line_color</PropertyName></ogc:Function>
                       <ogc:Literal>#FFFFFF</ogc:Literal>
                       <PropertyName>line_color</PropertyName>
                   </ogc:Function>
                   <PropertyName>text_color</PropertyName>
                </ogc:Function>
              </CssParameter>
            </Fill>
            <VendorOption name="maxDisplacement">400</VendorOption>
            <VendorOption name="partials">true</VendorOption>
            <VendorOption name="conflictResolution">false</VendorOption>
            <VendorOption name="spaceAround">-1</VendorOption>
            <VendorOption name="goodnessOfFit">0.1</VendorOption>
          </TextSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
"""

def ensure_dwg_style() -> tuple[bool, str]:
    """Ensure dwg_generic_style exists"""
    try:
        style_name = "dwg_generic_style"
        ws = settings.geoserver_workspace
        base = settings.geoserver_url.rstrip("/")
        # Check if style exists in workspace
        url = f"{base}/rest/workspaces/{ws}/styles/{style_name}.json"
        
        with httpx.Client(timeout=30.0) as client:
            h_sld = {**_auth_headers(), "Content-Type": "application/vnd.ogc.sld+xml"}
            
            r = client.get(url, headers=_auth_headers())
            if r.status_code == 200:
                # Update it to ensure latest SLD
                client.put(
                    f"{base}/rest/workspaces/{ws}/styles/{style_name}",
                    headers=h_sld,
                    content=DWG_SLD
                )
                return True, ""
                
            # Create style
            create_url = f"{base}/rest/workspaces/{ws}/styles"
            r2 = client.post(
                create_url, 
                params={"name": style_name},
                headers=h_sld,
                content=DWG_SLD
            )
            
            if r2.status_code in (200, 201):
                return True, ""
            return False, f"Create style failed: {r2.status_code} {r2.text[:200]}"
            
    except Exception as e:
        return False, str(e)


def ensure_workspace() -> tuple[bool, str]:
    """创建 workspace 若不存在"""
    try:
        url = _rest(f"workspaces/{settings.geoserver_workspace}.json")
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, headers=_auth_headers())
            if r.status_code == 200:
                return True, ""
            if r.status_code != 404:
                return False, f"检查 workspace 失败: {r.status_code} {r.text[:200]}"
            create_url = _rest("workspaces")
            body = {"workspace": {"name": settings.geoserver_workspace}}
            r2 = client.post(create_url, headers={**_auth_headers(), "Content-Type": "application/json"}, json=body)
            if r2.status_code not in (200, 201):
                return False, f"创建 workspace 失败: {r2.status_code} {r2.text[:200]}"
        return True, ""
    except Exception as e:
        return False, str(e)


def truncate_gwc_layer(layer_name: str) -> tuple[bool, str]:
    """Force clean GWC cache for a layer"""
    try:
        ws = settings.geoserver_workspace
        full_layer_name = f"{ws}:{layer_name}"
        base = settings.geoserver_url.rstrip("/")
        # Using masstruncate API
        url = f"{base}/gwc/rest/masstruncate"
        
        # Use ElementTree for safe XML construction
        root = ET.Element("truncateLayer")
        ET.SubElement(root, "layerName").text = full_layer_name
        body = ET.tostring(root, encoding="unicode")
        
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                url, 
                headers={**_auth_headers(), "Content-Type": "application/xml"}, 
                content=body
            )
            if r.status_code == 200:
                return True, ""
            return False, f"Cache cleanup failed: {r.status_code}"
    except Exception as e:
        return False, str(e)


def enable_gwc_mvt(layer_name: str) -> tuple[bool, str]:
    """
    配置 GWC 缓存，启用 application/vnd.mapbox-vector-tile 格式
    """
    try:
        ws = settings.geoserver_workspace
        full_layer_name = f"{ws}:{layer_name}"
        
        # GWC Layer Configuration URL (GeoServer internal GWC)
        # Endpoint: /geoserver/gwc/rest/layers/{layerName}
        base = settings.geoserver_url.rstrip("/")
        url = f"{base}/gwc/rest/layers/{full_layer_name}.xml"
        
        # Style name with workspace
        style_name = "dwg_generic_style"
        full_style_name = f"{ws}:{style_name}"

        # Build XML using ElementTree for safety
        root = ET.Element("GeoServerLayer")
        
        ET.SubElement(root, "enabled").text = "true"
        ET.SubElement(root, "inMemoryCached").text = "true"
        ET.SubElement(root, "name").text = full_layer_name
        ET.SubElement(root, "gutter").text = "100"
        
        mime_formats = ET.SubElement(root, "mimeFormats")
        for fmt in ["image/png", "image/jpeg", "application/vnd.mapbox-vector-tile"]:
            ET.SubElement(mime_formats, "string").text = fmt
            
        grid_subsets = ET.SubElement(root, "gridSubsets")
        
        # EPSG:900913
        gs_900913 = ET.SubElement(grid_subsets, "gridSubset")
        ET.SubElement(gs_900913, "gridSetName").text = "EPSG:900913"
        extent_900913 = ET.SubElement(gs_900913, "extent")
        coords_900913 = ET.SubElement(extent_900913, "coords")
        for val in ["-20037508.34", "-20037508.34", "20037508.34", "20037508.34"]:
            ET.SubElement(coords_900913, "double").text = val
            
        # EPSG:4326
        gs_4326 = ET.SubElement(grid_subsets, "gridSubset")
        ET.SubElement(gs_4326, "gridSetName").text = "EPSG:4326"
        extent_4326 = ET.SubElement(gs_4326, "extent")
        coords_4326 = ET.SubElement(extent_4326, "coords")
        for val in ["-180.0", "-90.0", "180.0", "90.0"]:
            ET.SubElement(coords_4326, "double").text = val
            
        meta = ET.SubElement(root, "metaWidthHeight")
        ET.SubElement(meta, "int").text = "4"
        ET.SubElement(meta, "int").text = "4"
        
        ET.SubElement(root, "expireCache").text = "0"
        ET.SubElement(root, "expireClients").text = "0"
        
        param_filters = ET.SubElement(root, "parameterFilters")
        spf = ET.SubElement(param_filters, "stringParameterFilter")
        ET.SubElement(spf, "key").text = "STYLES"
        ET.SubElement(spf, "defaultValue")
        values = ET.SubElement(spf, "values")
        ET.SubElement(values, "string") # Empty string
        ET.SubElement(values, "string").text = full_style_name
        
        xml_body = ET.tostring(root, encoding="unicode")

        with httpx.Client(timeout=30.0) as client:
            # Try to PUT (create/update)
            r = client.put(
                url, 
                headers={**_auth_headers(), "Content-Type": "application/xml"}, 
                content=xml_body
            )
            
            if r.status_code in (200, 201):
                return True, ""
            
            # If 404 on PUT (rare for GWC rest), try POST? 
            # Usually PUT to /layers/{name} works if it exists or creates it.
            # But official docs say POST to /layers to create.
            
            if r.status_code == 404:
                create_url = f"{base}/gwc/rest/layers"
                r2 = client.post(
                    create_url,
                    headers={**_auth_headers(), "Content-Type": "application/xml"},
                    content=xml_body
                )
                if r2.status_code in (200, 201):
                    return True, ""
                return False, f"GWC Layer 创建失败: {r2.status_code} {r2.text[:200]}"
                
            return False, f"GWC Layer 配置失败: {r.status_code} {r.text[:200]}"

    except Exception as e:
        return False, str(e)


def publish_gpkg(gpkg_path: Path, store_name: str, layer_name: str, native_layer_name: str = None) -> tuple[bool, str]:
    """
    将 GeoPackage 文件发布到 GeoServer。
    native_layer_name: GPKG 中的表名（若不提供，默认尝试自动推断或与 layer_name 相同）
    """
    try:
        gpkg_path = Path(gpkg_path).resolve()
        if not gpkg_path.exists():
            return False, "GeoPackage 文件不存在"
        
        # 0. Ensure style exists
        ok_style, msg_style = ensure_dwg_style()
        if not ok_style:
            return False, f"Style creation failed: {msg_style}"

        ws = settings.geoserver_workspace
        base = _rest("").rstrip("/rest")

        with httpx.Client(timeout=30.0) as client:
            h = _auth_headers()
            # 1. 创建 datastore (GeoPackage)
            store_url = _rest(f"workspaces/{ws}/datastores/{store_name}.json")
            # GeoServer 2.19+ 支持 GeoPackage：使用 file 存储，path 为 file:///path/to/file.gpkg
            # Connection Parameters (Flat format for recent GeoServer REST API)
            body = {
                "dataStore": {
                    "name": store_name,
                    "type": "GeoPackage",
                    "enabled": True,
                    "connectionParameters": {
                        "database": f"file://{gpkg_path.as_posix()}",
                        "dbtype": "geopackage"
                    },
                }
            }
            r = client.get(store_url, headers=h)
            if r.status_code == 404:
                create_store_url = _rest(f"workspaces/{ws}/datastores.json")
                r2 = client.post(
                    create_store_url,
                    headers={**h, "Content-Type": "application/json"},
                    json=body,
                )
                if r2.status_code not in (200, 201):
                    return False, f"创建 datastore 失败: {r2.status_code} {r2.text[:300]}"
            elif r.status_code != 200:
                return False, f"查询 datastore 失败: {r.status_code}"

            # 2. 发布图层
            layers_url = _rest(f"workspaces/{ws}/datastores/{store_name}/featuretypes.json")
            r3 = client.get(layers_url, headers=h)
            if r3.status_code != 200:
                return False, f"获取 feature types 失败: {r3.status_code} {r3.text[:200]}"
            
            try:
                data = r3.json()
                existing = data.get("featureTypes", {}).get("featureType", [])
                if isinstance(existing, dict):
                    existing = [existing]
                ft_name = existing[0]["name"] if existing else layer_name
            except Exception:
                ft_name = layer_name

            ft_url = _rest(f"workspaces/{ws}/datastores/{store_name}/featuretypes/{ft_name}.json")
            r4 = client.get(ft_url, headers=h)
            if r4.status_code == 404:
                create_ft_url = _rest(f"workspaces/{ws}/datastores/{store_name}/featuretypes.json")
                
                ft_body = {
                    "featureType": {
                        "name": layer_name,
                        "title": layer_name
                    }
                }
                if native_layer_name:
                    ft_body["featureType"]["nativeName"] = native_layer_name
                elif ft_name != layer_name:
                     # If we found an existing name, use it? No, we are creating.
                     pass
                
                r_create = client.post(
                    create_ft_url,
                    headers={**h, "Content-Type": "application/json"},
                    json=ft_body,
                )
                if r_create.status_code not in (200, 201):
                    return False, f"创建 featureType 失败: {r_create.status_code} {r_create.text[:200]}"
                
                # Update ft_name to the one we just created
                ft_name = layer_name

            # 2.5 Update layer styles
            # Do NOT set defaultStyle to dwg_generic_style as it breaks MVT filtering (MVT needs raw data).
            # Instead, add it to "styles" (Available Styles) so we can request it via STYLES param in raster mode.
            layer_url = _rest(f"workspaces/{ws}/layers/{ft_name}.json")
            layer_body = {
                "layer": {
                    # We do NOT touch defaultStyle, letting GeoServer pick a safe default (e.g. generic/point/line)
                    "styles": {
                        "style": [
                            { "name": "dwg_generic_style", "workspace": ws }
                        ]
                    }
                }
            }
            client.put(layer_url, headers={**h, "Content-Type": "application/json"}, json=layer_body)

        # 3. 启用 GWC MVT 缓存
        ok_gwc, msg_gwc = enable_gwc_mvt(ft_name)
        if not ok_gwc:
            return False, f"GWC 切片配置失败: {msg_gwc}"
        
        # 4. 清理旧缓存 (解决更新后显示旧数据问题)
        truncate_gwc_layer(ft_name)
            
        return True, ""
    except Exception as e:
        return False, str(e)


def get_mvt_url(layer_name: str) -> str:
    """返回该图层的 MVT 矢量切片 URL 模板（OpenLayers 等可用）"""
    # GeoServer GWC WMTS 矢量切片示例:
    # {base}/gwc/service/wmts?layer=workspace:layer&tilematrixset=EPSG:900913&...
    base = (settings.geoserver_public_url or settings.geoserver_url).rstrip("/")
    ws = settings.geoserver_workspace
    try:
        from urllib.parse import quote
        layer_param = quote(f"{ws}:{layer_name}")
    except Exception:
        layer_param = f"{ws}:{layer_name}"
    return (
        f"{base}/gwc/service/wmts?"
        f"layer={layer_param}"
        "&tilematrixset=EPSG:900913"
        "&Service=WMTS&Request=GetTile&Version=1.0.0"
        "&Format=application/vnd.mapbox-vector-tile"
        "&TileMatrix=EPSG:900913:{z}&TileRow={y}&TileCol={x}"
    )


def get_raster_url(layer_name: str) -> str:
    """返回该图层的 XYZ 栅格切片 URL 模板"""
    base = (settings.geoserver_public_url or settings.geoserver_url).rstrip("/")
    ws = settings.geoserver_workspace
    
    style_name = "dwg_generic_style"
    full_style_name = f"{ws}:{style_name}"
    
    try:
        from urllib.parse import quote
        layer_param = quote(f"{ws}:{layer_name}")
        style_param = quote(full_style_name)
    except Exception:
        layer_param = f"{ws}:{layer_name}"
        style_param = full_style_name
        
    return (
        f"{base}/gwc/service/wmts?"
        f"layer={layer_param}"
        "&tilematrixset=EPSG:900913"
        "&Service=WMTS&Request=GetTile&Version=1.0.0"
        "&Format=image/png"
        f"&style={style_param}"
        "&TileMatrix=EPSG:900913:{z}&TileRow={y}&TileCol={x}"
    )


def get_wmts_capabilities_url() -> str:
    """WMTS 能力文档 URL"""
    base = (settings.geoserver_public_url or settings.geoserver_url).rstrip("/")
    return f"{base}/gwc/service/wmts?request=GetCapabilities"

def ensure_dwg_raster_style() -> tuple[bool, str]:
    """Ensure dwg_raster_style exists (for raster tiles with better text/color)"""
    try:
        style_name = "dwg_raster_style"
        ws = settings.geoserver_workspace
        base = settings.geoserver_url.rstrip("/")
        # Check if style exists in workspace
        url = f"{base}/rest/workspaces/{ws}/styles/{style_name}.json"
        
        with httpx.Client(timeout=30.0) as client:
            h_sld = {**_auth_headers(), "Content-Type": "application/vnd.ogc.sld+xml"}
            
            r = client.get(url, headers=_auth_headers())
            if r.status_code == 200:
                # Update it to ensure latest SLD
                client.put(
                    f"{base}/rest/workspaces/{ws}/styles/{style_name}",
                    headers=h_sld,
                    content=DWG_RASTER_SLD
                )
                return True, ""
                
            # Create style
            create_url = f"{base}/rest/workspaces/{ws}/styles"
            r2 = client.post(
                create_url, 
                params={"name": style_name},
                headers=h_sld,
                content=DWG_RASTER_SLD
            )
            
            if r2.status_code in (200, 201):
                return True, ""
            return False, f"Create raster style failed: {r2.status_code} {r2.text[:200]}"
            
    except Exception as e:
        return False, str(e)


def _update_gwc_layer_styles(layer_name: str, style_name: str) -> None:
    """Helper to update GWC layer configuration to allow a style"""
    try:
        ws = settings.geoserver_workspace
        base = settings.geoserver_url.rstrip("/")
        full_layer_name = f"{ws}:{layer_name}"
        full_style_name = f"{ws}:{style_name}"
        
        url = f"{base}/gwc/rest/layers/{full_layer_name}.xml"
        
        with httpx.Client(timeout=10.0) as client:
            h = {**_auth_headers(), "Accept": "text/xml"}
            r = client.get(url, headers=h)
            if r.status_code != 200:
                print(f"Failed to get GWC layer config: {r.status_code}")
                return
                
            xml_content = r.text
            root = ET.fromstring(xml_content)
            updated = False
            
            # FIX: Ensure name is correct (fix encoding issues)
            name_elem = root.find("name")
            if name_elem is not None and name_elem.text != full_layer_name:
                print(f"Fixing GWC layer name from '{name_elem.text}' to '{full_layer_name}'")
                name_elem.text = full_layer_name
                updated = True

            # Find parameterFilters -> stringParameterFilter[key=STYLES] -> values
            param_filters = root.find("parameterFilters")
            if param_filters:
                for spf in param_filters.findall("stringParameterFilter"):
                    key = spf.find("key")
                    if key is not None and key.text == "STYLES":
                        values = spf.find("values")
                        if values is not None:
                            # Check if style already exists in values
                            existing_values = [v.text for v in values.findall("string")]
                            if full_style_name not in existing_values:
                                # Add new string value
                                new_val = ET.Element("string")
                                new_val.text = full_style_name
                                values.append(new_val)
                                updated = True
            
            if updated:
                # PUT back
                h_put = {**_auth_headers(), "Content-Type": "text/xml"}
                new_xml = ET.tostring(root, encoding="unicode")
                r_put = client.put(url, headers=h_put, content=new_xml)
                if r_put.status_code != 200:
                    print(f"Failed to update GWC layer: {r_put.status_code} {r_put.text}")
                
    except Exception as e:
        print(f"Error updating GWC layer styles: {e}")


def add_raster_style_to_layer(layer_name: str) -> tuple[bool, str]:
    """
    Associate dwg_raster_style with the layer so it can be used in WMS/WMTS requests.
    This does NOT change the default style (preserving MVT behavior).
    """
    try:
        ws = settings.geoserver_workspace
        base = settings.geoserver_url.rstrip("/")
        
        # 1. Ensure style exists
        ok, msg = ensure_dwg_raster_style()
        if not ok:
            return False, msg
            
        # 2. Add to layer
        layer_url = f"{base}/rest/workspaces/{ws}/layers/{layer_name}.json"
        with httpx.Client(timeout=30.0) as client:
            h = {**_auth_headers(), "Content-Type": "application/json"}
            
            # We must be careful not to overwrite existing styles, but here we know the structure.
            # We want "dwg_generic_style" AND "dwg_raster_style" available.
            
            layer_body = {
                "layer": {
                    "styles": {
                        "style": [
                            { "name": "dwg_generic_style", "workspace": ws },
                            { "name": "dwg_raster_style", "workspace": ws }
                        ]
                    }
                }
            }
            r = client.put(layer_url, headers=h, json=layer_body)
            if r.status_code == 200:
                # Ensure GWC also knows about this style
                _update_gwc_layer_styles(layer_name, "dwg_raster_style")
                return True, ""
            return False, f"Update layer styles failed: {r.status_code} {r.text[:200]}"
            
    except Exception as e:
        return False, str(e)


def get_raster_url_v2(layer_name: str) -> str:
    """Return XYZ raster tile URL using the new dwg_raster_style"""
    base = (settings.geoserver_public_url or settings.geoserver_url).rstrip("/")
    ws = settings.geoserver_workspace
    
    style_name = "dwg_raster_style"
    full_style_name = f"{ws}:{style_name}"
    
    try:
        from urllib.parse import quote
        layer_param = quote(f"{ws}:{layer_name}")
        style_param = quote(full_style_name)
    except Exception:
        layer_param = f"{ws}:{layer_name}"
        style_param = full_style_name
        
    return (
        f"{base}/gwc/service/wmts?"
        f"layer={layer_param}"
        "&tilematrixset=EPSG:900913"
        "&Service=WMTS&Request=GetTile&Version=1.0.0"
        "&Format=image/png"
        f"&style={style_param}"
        "&TileMatrix=EPSG:900913:{z}&TileRow={y}&TileCol={x}"
    )
