// chart_bridge.js -- the JS half of the chart_view.py <-> chart_host.html
// channel. Exposes renderFigure()/relayout(), called from Python via
// QWebEngineView.page().runJavaScript(), and forwards Plotly click/selection
// events back to Python through the "chartBridge" QWebChannel object (see
// src/ui/web/chart_bridge.py::ChartBridge).
//
// Click/selection forwarding has no Python-side consumer yet -- that lands
// in milestone 24, which filters a paired DataTableView from a chart click.
// The channel contract is defined now so chart_host.html does not need to
// change again then, matching how src/ui/theme/plotly_theme.py was built in
// milestone 15 and only wired into chart rendering here in milestone 16.
(function () {
  "use strict";

  var chartEl = document.getElementById("chart");
  var bridge = null;
  var rendered = false;

  function connectBridge() {
    // qt.webChannelTransport only exists inside a QWebEngineView that has
    // called page().setWebChannel(...) -- absent when this file is opened
    // as a plain local file (e.g. during manual debugging), in which case
    // rendering still works and forwarding is silently a no-op.
    if (typeof qt === "undefined" || !qt.webChannelTransport) {
      return;
    }
    new QWebChannel(qt.webChannelTransport, function (channel) {
      bridge = channel.objects.chartBridge || null;
    });
  }

  // Called from Python with three JSON-encoded strings (data, layout,
  // config) rather than one combined object -- layout is assembled
  // Python-side by merging the figure's own layout with
  // src.ui.theme.plotly_theme.plotly_layout(tokens), and keeping the pieces
  // separate here mirrors that split instead of re-merging it in JS too.
  window.renderFigure = function (dataJson, layoutJson, configJson) {
    var data = JSON.parse(dataJson);
    var layout = JSON.parse(layoutJson);
    var config = JSON.parse(configJson);
    if (!rendered) {
      Plotly.newPlot(chartEl, data, layout, config);
      rendered = true;
      chartEl.on("plotly_click", forwardClick);
      chartEl.on("plotly_selected", forwardSelection);
    } else {
      // Plotly.react diffs against the existing plot rather than
      // rebuilding the DOM from scratch -- this is what makes a re-render
      // (e.g. after a data update) not flicker the way a fresh newPlot()
      // would.
      Plotly.react(chartEl, data, layout, config);
    }
  };

  // Called on every theme toggle (src/ui/dock_manager.py, subscribed to
  // ThemeManager.theme_changed) with just the new layout -- Plotly.relayout
  // patches colours/fonts in place with no re-plot of the data traces
  // themselves, which is what keeps a theme switch from flickering.
  window.relayout = function (layoutJson) {
    if (!rendered) {
      return;
    }
    Plotly.relayout(chartEl, JSON.parse(layoutJson));
  };

  function forwardClick(evt) {
    if (!bridge || !evt || !evt.points || !evt.points.length) {
      return;
    }
    var point = evt.points[0];
    bridge.notify_point_clicked(
      JSON.stringify({
        curveNumber: point.curveNumber,
        pointIndex: point.pointIndex,
        x: point.x,
        y: point.y,
      })
    );
  }

  function forwardSelection(evt) {
    if (!bridge || !evt || !evt.points) {
      return;
    }
    var indices = evt.points.map(function (point) {
      return point.pointIndex;
    });
    bridge.notify_selection_changed(JSON.stringify(indices));
  }

  connectBridge();
})();
