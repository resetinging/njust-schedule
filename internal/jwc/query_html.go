package jwc

import (
	"context"
	"net/http"
	"net/url"

	"github.com/PuerkitoBio/goquery"
)

func (c *Client) getHTMLDocument(ctx context.Context, rawURL string) (*goquery.Document, error) {
	resp, err := c.request(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return nil, err
	}
	if c.isLoginPage(resp, raw) {
		return nil, ErrSessionExpired
	}
	return parseDocument(raw)
}

func (c *Client) postHTMLDocument(ctx context.Context, rawURL string, values url.Values) (*goquery.Document, error) {
	resp, err := c.request(ctx, http.MethodPost, rawURL, values)
	if err != nil {
		return nil, err
	}
	raw, err := readResponse(resp)
	if err != nil {
		return nil, err
	}
	if c.isLoginPage(resp, raw) {
		return nil, ErrSessionExpired
	}
	return parseDocument(raw)
}
